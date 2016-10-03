# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2015, Alex Băluț <alexandru.balut@gmail.com>
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
from unittest import mock

from gi.repository import Gdk
from gi.repository import GES
from gi.repository import Gtk

from pitivi.project import ProjectManager
from pitivi.timeline.timeline import TimelineContainer
from pitivi.utils import ui
from pitivi.utils.validate import Event
from tests import common


SEPARATOR_HEIGHT = 4
THIN = ui.LAYER_HEIGHT / 2
THICK = ui.LAYER_HEIGHT


class BaseTestTimeline(common.TestCase):

    def createTimeline(self):
        app = common.create_pitivi_mock()
        project_manager = ProjectManager(app)
        project_manager.newBlankProject()
        project = project_manager.current_project

        timeline_container = TimelineContainer(app)
        timeline_container.setProject(project)

        timeline = timeline_container.timeline
        timeline.app.project_manager.current_project = project
        timeline.get_parent = mock.MagicMock(return_value=timeline_container)

        timeline.app.settings.leftClickAlsoSeeks = False

        return timeline

    def addClipsSimple(self, timeline, num_clips):
        layer = timeline.ges_timeline.append_layer()
        asset = GES.UriClipAsset.request_sync(
            common.get_sample_uri("tears_of_steel.webm"))
        clips = [layer.add_asset(asset, i * 10, 0, 10, GES.TrackType.UNKNOWN)
                 for i in range(num_clips)]
        self.assertEqual(len(clips), num_clips)
        return clips


class TestLayers(BaseTestTimeline):

    def testDraggingLayer(self):
        self.checkGetLayerAt([THIN, THIN, THIN], 1, True,
                             [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2])
        self.checkGetLayerAt([THICK, THICK, THICK], 1, True,
                             [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2])
        self.checkGetLayerAt([THIN, THICK, THIN], 1, True,
                             [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2])
        self.checkGetLayerAt([THICK, THIN, THICK], 1, True,
                             [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2])

    def testDraggingClipFromLayer(self):
        self.checkGetLayerAt([THIN, THIN, THIN], 1, False,
                             [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2])
        self.checkGetLayerAt([THICK, THICK, THICK], 1, False,
                             [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2])
        self.checkGetLayerAt([THIN, THICK, THIN], 1, False,
                             [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2])
        self.checkGetLayerAt([THICK, THIN, THICK], 1, False,
                             [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2])

    def testDraggingClipFromOuterSpace(self):
        self.checkGetLayerAt([THIN, THIN, THIN], None, False,
                             [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2])
        self.checkGetLayerAt([THICK, THICK, THICK], None, False,
                             [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2])
        self.checkGetLayerAt([THIN, THICK, THIN], None, False,
                             [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2])
        self.checkGetLayerAt([THICK, THIN, THICK], None, False,
                             [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2])

    def checkGetLayerAt(self, heights, preferred, past_middle_when_adjacent, expectations):
        timeline = self.createTimeline()

        y = 0
        for priority, height in enumerate(heights):
            ges_layer = timeline.createLayer(priority=priority)
            rect = Gdk.Rectangle()
            rect.y = y
            rect.height = height
            ges_layer.ui.set_allocation(rect)
            y += height + SEPARATOR_HEIGHT

        ges_layers = [layer.ges_layer for layer in timeline._layers]
        if preferred is None:
            preferred_ges_layer = None
        else:
            preferred_ges_layer = ges_layers[preferred]
        h = [layer.get_allocation().height for layer in timeline._layers]
        s = SEPARATOR_HEIGHT

        def assertLayerAt(ges_layer, y):
            result = timeline._get_layer_at(
                int(y),
                prefer_ges_layer=preferred_ges_layer,
                past_middle_when_adjacent=past_middle_when_adjacent)
            self.assertEqual(
                ges_layer,
                result[0],
                "Expected %d, got %d at %d" % (ges_layers.index(ges_layer), ges_layers.index(result[0]), y))

        # y on the top layer.
        assertLayerAt(ges_layers[expectations[0]], 0)
        assertLayerAt(ges_layers[expectations[1]], h[0] / 2 - 1)
        assertLayerAt(ges_layers[expectations[2]], h[0] / 2)
        assertLayerAt(ges_layers[expectations[3]], h[0] - 1)

        # y on the separator.
        assertLayerAt(ges_layers[expectations[4]], h[0])
        assertLayerAt(ges_layers[expectations[5]], h[0] + s - 1)

        # y on the middle layer.
        assertLayerAt(ges_layers[expectations[6]], h[0] + s)
        assertLayerAt(ges_layers[expectations[7]], h[0] + s + h[1] / 2 - 1)
        assertLayerAt(ges_layers[expectations[8]], h[0] + s + h[1] / 2)
        assertLayerAt(ges_layers[expectations[9]], h[0] + s + h[1] - 1)

        # y on the separator.
        assertLayerAt(ges_layers[expectations[10]], h[0] + s + h[1])
        assertLayerAt(ges_layers[expectations[11]], h[0] + s + h[1] + s - 1)

        # y on the bottom layer.
        assertLayerAt(ges_layers[expectations[12]], h[0] + s + h[1] + s)
        assertLayerAt(ges_layers[expectations[13]], h[0] + s + h[1] + s + h[2] / 2 - 1)
        assertLayerAt(ges_layers[expectations[14]], h[0] + s + h[1] + s + h[2] / 2)
        assertLayerAt(ges_layers[expectations[15]], h[0] + s + h[1] + s + h[2] - 1)

    def testSetSeparatorsPrelight(self):
        timeline = self.createTimeline()
        timeline.__on_separators = [mock.Mock()]
        timeline._setSeparatorsPrelight(False)
        self.assertEqual(len(timeline.__on_separators), 1,
                         "The separators must be forgotten only in dragEnd()")


class TestGrouping(BaseTestTimeline):

    def groupClips(self, num_clips):
        timeline = self.createTimeline()
        timeline.app.settings.leftClickAlsoSeeks = False
        clips = self.addClipsSimple(timeline, num_clips)

        # Press <ctrl> so selecting in ADD mode
        timeline.sendFakeEvent(Event(event_type=Gdk.EventType.KEY_PRESS,
                                     keyval=Gdk.KEY_Control_L))

        # Select the 2 clips
        for clip in clips:
            self.toggleClipSelection(clip, expect_selected=True)

        before_grouping_timeline_group = timeline.current_group

        for clip in clips:
            self.assertEqual(clip.get_parent(), timeline.current_group)

        timeline.parent.group_action.emit("activate", None)

        self.assertNotEqual(timeline.current_group, before_grouping_timeline_group)
        for clip in clips:
            # Check that we created a new group and that this group is not
            # the timeline current_group
            self.assertTrue(isinstance(clip.get_parent(), GES.Group))
            self.assertNotEqual(clip.get_parent(), timeline.current_group)
            # The newly created group has been selected
            self.assertEqual(clip.get_toplevel_parent(), timeline.current_group)

        for clip in clips:
            self.assertEqual(clips[0].get_parent(), clip.get_parent())
            self.assertTrue(bool(clip.ui.get_state_flags() & Gtk.StateFlags.SELECTED))
            self.assertTrue(clip.selected.selected)

        group = clips[0].get_parent()
        self.assertEqual(len(group.get_children(False)), num_clips)

        return timeline

    def testGroup(self):
        self.groupClips(2)

    def testGroupSelection(self):
        num_clips = 2
        timeline = self.groupClips(num_clips)
        layer = timeline.ges_timeline.get_layers()[0]
        clips = layer.get_clips()
        self.assertEqual(len(clips), num_clips)

        # Deselect one grouped clip clips
        self.toggleClipSelection(clips[0], expect_selected=False)

        # Make sure all the clips have been deselected
        for clip in clips:
            self.assertFalse(bool(clip.ui.get_state_flags() & Gtk.StateFlags.SELECTED))
            self.assertFalse(clip.selected.selected)

    def testGroupUngroup(self):
        num_clips = 2
        timeline = self.groupClips(num_clips)

        self.assertEqual(len(timeline.selection.selected), num_clips)

        timeline.parent.ungroup_action.emit("activate", None)
        layer = timeline.ges_timeline.get_layers()[0]
        clips = layer.get_clips()
        self.assertEqual(len(clips), num_clips)

        for clip in clips:
            self.assertIsNone(clip.get_parent())

    def testGroupSplittedClipAndSelectGroup(self):
        position = 5

        timeline = self.createTimeline()
        clips = self.addClipsSimple(timeline, 1)
        self.toggleClipSelection(clips[0], expect_selected=True)

        timeline.ges_timeline.get_asset().pipeline.getPosition = mock.Mock(return_value=position)
        layer = timeline.ges_timeline.get_layers()[0]

        # Split
        timeline.parent.split_action.emit("activate", None)
        clips = layer.get_clips()
        self.assertEqual(len(clips), 2)

        # Only the first clip is selected so select the
        # second one
        self.assertTrue(clips[0].selected.selected)
        self.assertFalse(clips[1].selected.selected)

        timeline.sendFakeEvent(Event(event_type=Gdk.EventType.KEY_PRESS,
                                     keyval=Gdk.KEY_Control_L))
        self.toggleClipSelection(clips[1], expect_selected=True)
        timeline.sendFakeEvent(Event(event_type=Gdk.EventType.KEY_RELEASE,
                                     keyval=Gdk.KEY_Control_L))

        for clip in clips:
            self.assertTrue(clip.selected.selected)

        # Group the two parts
        timeline.parent.group_action.emit("activate", None)

        self.toggleClipSelection(clips[1], expect_selected=True)

    def testUngroupClip(self):
        timeline = self.createTimeline()
        ges_clip, = self.addClipsSimple(timeline, 1)

        self.toggleClipSelection(ges_clip, expect_selected=True)

        timeline.parent.ungroup_action.emit("activate", None)
        layer = timeline.ges_timeline.get_layers()[0]
        ges_clip0, ges_clip1 = layer.get_clips()

        self.assertEqual(ges_clip0.props.start, ges_clip1.props.start)
        self.assertEqual(ges_clip0.props.duration, ges_clip1.props.duration)

        bTrackElem0, = ges_clip0.get_children(recursive=False)
        bTrackElem1, = ges_clip1.get_children(recursive=False)

        if bTrackElem0.get_track_type() == GES.TrackType.AUDIO:
            aclip = ges_clip0.ui
            atrackelem = bTrackElem0.ui
            vclip = ges_clip1.ui
            vtrackelem = bTrackElem1.ui
        else:
            aclip = ges_clip1.ui
            atrackelem = bTrackElem1.ui

            vclip = ges_clip0.ui
            vtrackelem = bTrackElem0.ui

        self.assertEqual(aclip._audioSource, atrackelem)
        self.assertEqual(vclip._videoSource, vtrackelem)


class TestCopyPaste(BaseTestTimeline):

    def copyClips(self, num_clips):
        timeline = self.createTimeline()

        clips = self.addClipsSimple(timeline, num_clips)

        # Press <ctrl> so selecting in ADD mode
        timeline.sendFakeEvent(Event(event_type=Gdk.EventType.KEY_PRESS,
                                     keyval=Gdk.KEY_Control_L))

        # Select the 2 clips
        for clip in clips:
            self.toggleClipSelection(clip, expect_selected=True)

        self.assertTrue(timeline.parent.copy_action.props.enabled)
        self.assertFalse(timeline.parent.paste_action.props.enabled)
        timeline.parent.copy_action.emit("activate", None)
        self.assertTrue(timeline.parent.paste_action.props.enabled)

        return timeline

    def testCopyPaste(self):
        position = 20

        timeline = self.copyClips(2)

        layer = timeline.ges_timeline.get_layers()[0]
        # Monkey patching the pipeline.getPosition method
        project = timeline.ges_timeline.get_asset()
        project.pipeline.getPosition = mock.Mock(return_value=position)

        clips = layer.get_clips()
        self.assertEqual(len(clips), 2)

        timeline.parent.paste_action.emit("activate", None)

        n_clips = layer.get_clips()
        self.assertEqual(len(n_clips), 4)

        copied_clips = [clip for clip in n_clips if clip not in clips]
        self.assertEqual(len(copied_clips), 2)
        self.assertEqual(copied_clips[0].props.start, position)
        self.assertEqual(copied_clips[1].props.start, position + 10)


class TestEditing(BaseTestTimeline):

    def test_trimming_on_layer_separator(self):
        # Create a clip
        timeline = self.createTimeline()
        clip, = self.addClipsSimple(timeline, 1)
        layer = clip.get_layer()

        # Click the right trim handle of the clip.
        with mock.patch.object(timeline, 'get_event_widget') as get_event_widget:
            event = mock.Mock()
            event.get_button.return_value = True, 1
            get_event_widget.return_value = clip.ui.rightHandle
            timeline._button_press_event_cb(None, event)
            self.assertIsNotNone(timeline.draggingElement)

            # Drag it to the left, on the separator below.
            event = mock.Mock()
            event.get_state.return_value = Gdk.ModifierType.BUTTON1_MASK
            with mock.patch.object(clip.ui.rightHandle, "translate_coordinates") as translate_coordinates:
                translate_coordinates.return_value = (0, 0)
                with mock.patch.object(timeline, "_get_layer_at") as _get_layer_at:
                    _get_layer_at.return_value = layer, [layer.ui.after_sep]
                    timeline._motion_notify_event_cb(None, event)
            self.assertTrue(timeline.got_dragged)

        # Release the mouse button.
        event = mock.Mock()
        event.get_button.return_value = True, 1
        timeline._button_release_event_cb(None, event)
        self.assertEqual(len(timeline.ges_timeline.get_layers()), 1,
                         "No new layer should have been created")
