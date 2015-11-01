# Pitivi video editor
#
#       pitivi/clipproperties.py
#
# Copyright (C) 2010 Thibault Saunier <tsaunier@gnome.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA 02110-1301, USA.

import os

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import Pango
from gi.repository import GES

from gettext import gettext as _

from pitivi.configure import get_ui_dir

from pitivi.utils.ui import EFFECT_TARGET_ENTRY
from pitivi.utils.loggable import Loggable
from pitivi.utils.ui import PADDING, SPACING

from pitivi.effects import AUDIO_EFFECT, VIDEO_EFFECT, HIDDEN_EFFECTS, \
    EffectsPropertiesManager


(COL_ACTIVATED,
 COL_TYPE,
 COL_BIN_DESCRIPTION_TEXT,
 COL_NAME_TEXT,
 COL_DESC_TEXT,
 COL_TRACK_EFFECT) = list(range(6))


class ClipPropertiesError(Exception):
    """Base Exception for errors happening in L{ClipProperties}s or L{EffectProperties}s"""
    pass


class ClipProperties(Gtk.Box, Loggable):
    """
    Widget for configuring the selected clip.

    @type app: L{Pitivi}
    """

    def __init__(self, app):
        Gtk.Box.__init__(self)
        Loggable.__init__(self)
        self.app = app

        self.set_orientation(Gtk.Orientation.VERTICAL)

        self.infobar_box = Gtk.Box()
        self.infobar_box.set_orientation(Gtk.Orientation.VERTICAL)
        self.infobar_box.show()
        self.pack_start(self.infobar_box, False, False, 0)

        transformation_expander = TransformationProperties(app)
        transformation_expander.set_vexpand(False)
        self.pack_start(transformation_expander, False, False, 0)

        viewport = Gtk.ScrolledWindow()
        viewport.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        viewport.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        viewport.set_visible(True)

        self.effect_expander = EffectProperties(app, self)
        self.effect_expander.set_vexpand(False)
        viewport.add(self.effect_expander)
        self.pack_start(viewport, True, True, 0)

    def createInfoBar(self, text):
        label = Gtk.Label(label=text)
        label.set_line_wrap(True)
        infobar = Gtk.InfoBar()
        infobar.props.message_type = Gtk.MessageType.OTHER
        infobar.get_content_area().add(label)
        self.infobar_box.pack_start(infobar, False, False, 0)
        return infobar


class EffectProperties(Gtk.Expander, Loggable):
    """
    Widget for viewing a list of effects and configuring them.

    @type app: C{Pitivi}
    @type effects_properties_manager: C{EffectsPropertiesManager}
    """

    def __init__(self, app, clip_properties):
        Gtk.Expander.__init__(self)
        self.set_expanded(True)
        self.set_label(_("Effects"))
        Loggable.__init__(self)

        # Global variables related to effects
        self.app = app

        self._project = None
        self._selection = None
        self.selected_effects = []
        self.clips = []
        self._effect_config_ui = None
        self.effects_properties_manager = EffectsPropertiesManager(app)
        self.clip_properties = clip_properties
        self._config_ui_h_pos = None

        # The toolbar that will go between the list of effects and properties
        self._toolbar = Gtk.Toolbar()
        self._toolbar.get_style_context().add_class(
            Gtk.STYLE_CLASS_INLINE_TOOLBAR)
        self._toolbar.set_icon_size(Gtk.IconSize.SMALL_TOOLBAR)
        removeEffectButton = Gtk.ToolButton()
        removeEffectButton.set_icon_name("list-remove-symbolic")
        removeEffectButton.set_label(_("Remove effect"))
        removeEffectButton.set_is_important(True)
        self._toolbar.insert(removeEffectButton, 0)

        # Treeview to display a list of effects (checkbox, effect type and
        # name)
        self.treeview_scrollwin = Gtk.ScrolledWindow()
        self.treeview_scrollwin.set_policy(Gtk.PolicyType.NEVER,
                                           Gtk.PolicyType.AUTOMATIC)
        self.treeview_scrollwin.set_shadow_type(Gtk.ShadowType.ETCHED_IN)

        # We need to specify Gtk.TreeDragSource because otherwise we are hitting
        # bug https://bugzilla.gnome.org/show_bug.cgi?id=730740.
        class EffectsListStore(Gtk.ListStore, Gtk.TreeDragSource):
            def __init__(self, *args):
                Gtk.ListStore.__init__(self, *args)
                # Simply set the source index on the storemodrel directly
                # to avoid issues with the selection_data API
                # FIXME: Work around https://bugzilla.gnome.org/show_bug.cgi?id=737587
                self.source_index = None

            def do_drag_data_get(self, path, selection_data):
                self.source_index = path.get_indices()[0]

        self.storemodel = EffectsListStore(bool, str, str, str, str, object)
        self.treeview = Gtk.TreeView(model=self.storemodel)
        self.treeview_scrollwin.add(self.treeview)
        self.treeview.set_property("has_tooltip", True)
        self.treeview.set_headers_clickable(False)
        self.treeview.get_selection().set_mode(Gtk.SelectionMode.SINGLE)

        activatedcell = Gtk.CellRendererToggle()
        activatedcell.props.xpad = PADDING
        activatedcell.connect("toggled", self._effectActiveToggleCb)
        self.treeview.insert_column_with_attributes(-1,
                                                    _("Active"), activatedcell, active=COL_ACTIVATED)

        typecol = Gtk.TreeViewColumn(_("Type"))
        typecol.set_spacing(SPACING)
        typecol.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
        typecell = Gtk.CellRendererText()
        typecell.props.xpad = PADDING
        typecell.set_property("ellipsize", Pango.EllipsizeMode.END)
        typecol.pack_start(typecell, True)
        typecol.add_attribute(typecell, "text", COL_TYPE)
        self.treeview.append_column(typecol)

        namecol = Gtk.TreeViewColumn(_("Effect name"))
        namecol.set_spacing(SPACING)
        namecell = Gtk.CellRendererText()
        namecell.props.xpad = PADDING
        namecell.set_property("ellipsize", Pango.EllipsizeMode.END)
        namecol.pack_start(namecell, True)
        namecol.add_attribute(namecell, "text", COL_NAME_TEXT)
        self.treeview.append_column(namecol)

        # Allow the treeview to accept EFFECT_TARGET_ENTRY when drag&dropping.
        self.treeview.enable_model_drag_dest([EFFECT_TARGET_ENTRY],
                                             Gdk.DragAction.COPY)

        # Enable reordering by drag&drop.
        self.treeview.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK,
                                               [EFFECT_TARGET_ENTRY],
                                               Gdk.DragAction.MOVE)

        self.treeview_selection = self.treeview.get_selection()

        self._infobar = clip_properties.createInfoBar(
            _("Select a clip on the timeline to configure its associated effects"))

        # Prepare the main container widgets and lay out everything
        self._vcontent = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.pack_start(self.treeview_scrollwin, expand=True, fill=True, padding=0)
        vbox.pack_start(self._toolbar, expand=False, fill=False, padding=0)
        self._vcontent.pack1(vbox, resize=True, shrink=False)
        self.add(self._vcontent)
        self._vcontent.show()
        vbox.show_all()
        self._infobar.show_all()
        self._toolbar.hide()
        self.hide()

        # Connect all the widget signals
        self.treeview_selection.connect("changed", self._treeviewSelectionChangedCb)
        self.treeview.connect("drag-motion", self._dragMotionCb)
        self.treeview.connect("drag-leave", self._dragLeaveCb)
        self.treeview.connect("drag-data-received", self._dragDataReceivedCb)
        self.treeview.connect("query-tooltip", self._treeViewQueryTooltipCb)
        self._vcontent.connect("notify", self._vcontentNotifyCb)
        removeEffectButton.connect("clicked", self._removeEffectCb)
        self.app.project_manager.connect(
            "new-project-loaded", self._newProjectLoadedCb)
        self.connect('notify::expanded', self._expandedCb)

    def _newProjectLoadedCb(self, unused_app, project, unused_fully_loaded):
        if self._selection is not None:
            self._selection.disconnect_by_func(self._selectionChangedCb)
            self._selection = None
        self._project = project
        if project:
            self._selection = project.timeline.ui.selection
            self._selection.connect('selection-changed', self._selectionChangedCb)
            self.selected_effects = self._selection.getSelectedEffects()
        self.updateAll()

    def _vcontentNotifyCb(self, paned, gparamspec):
        if gparamspec and gparamspec.name == 'position':
            self._config_ui_h_pos = self._vcontent.get_position()
            self.app.settings.effectVPanedPosition = self._config_ui_h_pos

    def _selectionChangedCb(self, selection):
        for clip in self.clips:
            clip.disconnect_by_func(self._trackElementAddedCb)
            clip.disconnect_by_func(self._trackElementRemovedCb)

        self.selected_effects = selection.getSelectedEffects()

        if selection:
            self.clips = list(selection.selected)
            for clip in self.clips:
                clip.connect("child-added", self._trackElementAddedCb)
                clip.connect("child-removed", self._trackElementRemovedCb)
            self.show()
        else:
            self.clips = []
            self.hide()
        self.updateAll()

    def _trackElementAddedCb(self, unused_clip, track_element):
        if isinstance(track_element, GES.BaseEffect):
            selec = self._selection.getSelectedEffects()
            self.selected_effects = selec
            self.updateAll()

    def _trackElementRemovedCb(self, unused_clip, track_element):
        if isinstance(track_element, GES.BaseEffect):
            selec = self._selection.getSelectedEffects()
            self.selected_effects = selec
            self.updateAll()

    def _removeEffectCb(self, toolbutton):
        if not self.treeview_selection.get_selected()[1]:
            # Cannot remove nothing,
            return
        effect = self.storemodel.get_value(self.treeview_selection.get_selected()[1],
                                           COL_TRACK_EFFECT)
        self._removeEffect(effect)

    def _removeEffect(self, effect):
        self.app.action_log.begin("remove effect")
        self._removeEffectConfigurationWidget()
        self.effects_properties_manager.cleanCache(effect)
        effect.get_parent().remove(effect)
        self._project.timeline.commit()
        self.app.action_log.commit()
        self._updateTreeview()

    def addEffectToClip(self, clip, factory_name, priority=None):
        """Adds the specified effect if it can be applied to the clip."""
        model = self.treeview.get_model()
        media_type = self.app.effects.getInfo(factory_name).media_type
        for track_element in clip.get_children(False):
            track_type = track_element.get_track_type()
            if track_type == GES.TrackType.AUDIO and media_type == AUDIO_EFFECT or \
                    track_type == GES.TrackType.VIDEO and media_type == VIDEO_EFFECT:
                # Actually add the effect
                self.app.action_log.begin("add effect")
                effect = GES.Effect.new(bin_description=factory_name)
                clip.add(effect)
                if priority is not None and priority < len(model):
                    clip.set_top_effect_priority(effect, priority)
                self._project.timeline.commit()
                self.app.action_log.commit()
                self.updateAll()
                break

    def addEffectToCurrentSelection(self, factory_name):
        if not self.clips or len(self.clips) > 1:
            return
        clip = self.clips[0]
        # Checking that this effect can be applied on this track object
        # Which means, it has the corresponding media_type
        self.addEffectToClip(clip, factory_name)

    def _dragMotionCb(self, unused_tree_view, unused_drag_context, unused_x, unused_y, unused_timestamp):
        self.debug(
            "Something is being dragged in the clip properties' effects list")
        self.drag_highlight()

    def _dragLeaveCb(self, unused_tree_view, unused_drag_context, unused_timestamp):
        self.info(
            "The item being dragged has left the clip properties' effects list")
        self.drag_unhighlight()

    def _dragDataReceivedCb(self, treeview, drag_context, x, y, selection_data, unused_info, timestamp):
        if not self.clips or len(self.clips) > 1:
            # Indicate that a drop will not be accepted.
            Gdk.drag_status(drag_context, 0, timestamp)
            return
        clip = self.clips[0]
        model = treeview.get_model()
        if drag_context.get_suggested_action() == Gdk.DragAction.COPY:
            # An effect dragged probably from the effects list.
            factory_name = str(selection_data.get_data(), "UTF-8")
            # Target
            dest_row = treeview.get_dest_row_at_pos(x, y)
            if dest_row:
                drop_path, drop_pos = dest_row
                drop_index = drop_path.get_indices()[0]
                if drop_pos != Gtk.TreeViewDropPosition.BEFORE:
                    drop_index += 1
            else:
                # This should happen when dragging after the last row.
                drop_index = None
            self.addEffectToClip(clip, factory_name, drop_index)
        elif drag_context.get_suggested_action() == Gdk.DragAction.MOVE:
            # An effect dragged from the same treeview to change its position.
            # Source
            source_index = self.storemodel.source_index
            self.storemodel.source_index = None
            # Target
            dest_row = treeview.get_dest_row_at_pos(x, y)
            if dest_row:
                drop_path, drop_pos = dest_row
                drop_index = drop_path.get_indices()[0]
                drop_index = self.calculateEffectPriority(
                    source_index, drop_index, drop_pos)
            else:
                # This should happen when dragging after the last row.
                drop_index = len(model) - 1
                drop_pos = Gtk.TreeViewDropPosition.INTO_OR_BEFORE
            self.moveEffect(clip, source_index, drop_index)
        drag_context.finish(True, False, timestamp)

    def moveEffect(self, clip, source_index, drop_index):
        if source_index == drop_index:
            # Noop.
            return
        # The paths are different.
        effects = clip.get_top_effects()
        effect = effects[source_index]
        self.app.action_log.begin("move effect")
        clip.set_top_effect_priority(effect, drop_index)
        self._project.timeline.commit()
        self.app.action_log.commit()
        self._project.pipeline.flushSeek()
        new_path = Gtk.TreePath.new()
        new_path.append_index(drop_index)
        self.updateAll(path=new_path)

    @staticmethod
    def calculateEffectPriority(source_index, drop_index, drop_pos):
        """
        Return where the effect from source_index will end up
        """
        if drop_pos in (Gtk.TreeViewDropPosition.INTO_OR_BEFORE, Gtk.TreeViewDropPosition.INTO_OR_AFTER):
            return drop_index
        if drop_pos == Gtk.TreeViewDropPosition.BEFORE:
            if source_index < drop_index:
                return drop_index - 1
        elif drop_pos == Gtk.TreeViewDropPosition.AFTER:
            if source_index > drop_index:
                return drop_index + 1
        return drop_index

    def _effectActiveToggleCb(self, cellrenderertoggle, path):
        iter = self.storemodel.get_iter(path)
        tck_effect = self.storemodel.get_value(iter, COL_TRACK_EFFECT)
        self.app.action_log.begin("change active state")
        tck_effect.set_active(not tck_effect.is_active())
        cellrenderertoggle.set_active(tck_effect.is_active())
        self._updateTreeview()
        self._project.timeline.commit()
        self.app.action_log.commit()

    def _expandedCb(self, expander, params):
        self.updateAll()

    def _treeViewQueryTooltipCb(self, view, x, y, keyboard_mode, tooltip):
        is_row, x, y, model, path, tree_iter = view.get_tooltip_context(
            x, y, keyboard_mode)
        if not is_row:
            return False

        view.set_tooltip_row(tooltip, path)
        description = self.storemodel.get_value(tree_iter, COL_DESC_TEXT)
        bin_description = self.storemodel.get_value(
            tree_iter, COL_BIN_DESCRIPTION_TEXT)
        tooltip.set_text("%s\n%s" % (bin_description, description))
        return True

    def updateAll(self, path=None):
        if len(self.clips) == 1:
            self.show()
            self._infobar.hide()
            self._updateTreeview()
            if path:
                self.treeview_selection.select_path(path)
            self._vcontent.show()
        else:
            self.hide()
            self._removeEffectConfigurationWidget()
            self.storemodel.clear()
            self._infobar.show()
            self._vcontent.hide()

    def _updateTreeview(self):
        self.storemodel.clear()
        clip = self.clips[0]
        for effect in clip.get_top_effects():
            if effect.props.bin_description in HIDDEN_EFFECTS:
                continue
            effect_info = self.app.effects.getInfo(effect.props.bin_description)
            to_append = [effect.props.active]
            track_type = effect.get_track_type()
            if track_type == GES.TrackType.AUDIO:
                to_append.append("Audio")
            elif track_type == GES.TrackType.VIDEO:
                to_append.append("Video")
            to_append.append(effect.props.bin_description)
            to_append.append(effect_info.human_name)
            to_append.append(effect_info.description)
            to_append.append(effect)
            self.storemodel.append(to_append)

    def _treeviewSelectionChangedCb(self, treeview):
        if self.treeview_selection.count_selected_rows() == 0:
            self._toolbar.hide()
        else:
            self._toolbar.show()

        self._updateEffectConfigUi()

    def _updateEffectConfigUi(self):
        if self._config_ui_h_pos is None:
            self._config_ui_h_pos = self.app.gui.settings.effectVPanedPosition
            if self._config_ui_h_pos is None:
                self._config_ui_h_pos = self.app.gui.settings.mainWindowHeight // 3

        model, tree_iter = self.treeview_selection.get_selected()
        if tree_iter:
            effect = model.get_value(tree_iter, COL_TRACK_EFFECT)
            self._showEffectConfigurationWidget(effect)
        else:
            self._removeEffectConfigurationWidget()

    def _removeEffectConfigurationWidget(self):
        if not self._effect_config_ui:
            # Nothing to remove.
            return

        viewport = self._effect_config_ui.get_children()[0]
        element_settings_widget = viewport.get_children()[0]
        element_settings_widget.resetKeyframeToggleButtons()

        self._vcontent.remove(self._effect_config_ui)
        self._effect_config_ui = None

    def _showEffectConfigurationWidget(self, effect):
        self._removeEffectConfigurationWidget()
        self._effect_config_ui = self.effects_properties_manager.getEffectConfigurationUI(
            effect)
        if not self._effect_config_ui:
            return
        self._vcontent.pack2(
            self._effect_config_ui, resize=False, shrink=False)
        self._vcontent.set_position(int(self._config_ui_h_pos))
        self._effect_config_ui.show_all()


class TransformationProperties(Gtk.Expander, Loggable):
    """
    Widget for viewing and configuring speed
    """

    __signals__ = {
        'selection-changed': []}

    def __init__(self, app):
        Gtk.Expander.__init__(self)
        Loggable.__init__(self)
        self.app = app
        self._project = None
        self._selection = None
        self.source = None
        self._selected_clip = None
        self.spin_buttons = {}
        self.default_values = {}
        self.set_label(_("Transformation"))

        self.builder = Gtk.Builder()
        self.builder.add_from_file(os.path.join(get_ui_dir(),
                                                "cliptransformation.ui"))

        self.add(self.builder.get_object("transform_box"))
        self.show_all()
        self._initButtons()
        self.hide()

        self.app.project_manager.connect(
            "new-project-loaded", self._newProjectLoadedCb)

    def _newProjectLoadedCb(self, app, project, unused_fully_loaded):
        if self._selection is not None:
            self._selection.disconnect_by_func(self._selectionChangedCb)
            self._selection = None
        self._project = project
        if project:
            self._selection = project.timeline.ui.selection
            self._selection.connect('selection-changed', self._selectionChangedCb)

    def _initButtons(self):
        clear_button = self.builder.get_object("clear_button")
        clear_button.connect("clicked", self._defaultValuesCb)

        self.__setupSpinButton("xpos_spinbtn", "posx")
        self.__setupSpinButton("ypos_spinbtn", "posy")

        self.__setupSpinButton("width_spinbtn", "width")
        self.__setupSpinButton("height_spinbtn", "height")

    def _defaultValuesCb(self, widget):
        for name, spinbtn in list(self.spin_buttons.items()):
            spinbtn.set_value(self.default_values[name])

    def __sourcePropertyChangedCb(self, source, element, param):
        try:
            spin = self.spin_buttons[param.name]
        except KeyError:
            return

        res, value = self.source.get_child_property(param.name)
        if spin.get_value() != value:
            spin.set_value(value)

    def _updateSpinButtons(self):
        for name, spinbtn in list(self.spin_buttons.items()):
            res, value = self.source.get_child_property(name)
            assert(res)
            if name == "width":
                self.default_values[name] = self._project.videowidth
            elif name == "height":
                self.default_values[name] = self._project.videoheight
            else:
                self.default_values[name] = 0
            spinbtn.set_value(value)

    def __setupSpinButton(self, widget_name, property_name):
        """
        Create a spinbutton widget and connect its signals to change property
        values. While focused, disable the timeline actions' sensitivity.
        """
        spinbtn = self.builder.get_object(widget_name)
        spinbtn.connect("output", self._onValueChangedCb, property_name)
        self.spin_buttons[property_name] = spinbtn

    def _onValueChangedCb(self, spinbtn, prop):
        if not self.source:
            return

        value = spinbtn.get_value()

        res, cvalue = self.source.get_child_property(prop)
        if value != cvalue:
            self.app.action_log.begin("Transformation property change")
            self.source.set_child_property(prop, value)
            self.app.action_log.commit()
            self._project.pipeline.commit_timeline()

    def __setSource(self, source):
        if self.source:
            try:
                self.source.disconnect_by_func(self.__sourcePropertyChangedCb)
            except TypeError:
                pass
        self.source = source
        if self.source:
            self._updateSpinButtons()
            self.source.connect("deep-notify", self.__sourcePropertyChangedCb)

    def _selectionChangedCb(self, unused_timeline):
        if len(self._selection) == 1:
            clip = list(self._selection)[0]
            source = clip.find_track_element(None, GES.VideoSource)
            if source:
                self._selected_clip = clip
                self.__setSource(source)
                self.show()
                return

        # Deselect
        if self._selected_clip:
            self._selected_clip = None
            self._project.pipeline.flushSeek()
        self.__setSource(None)
        self.hide()
