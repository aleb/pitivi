# Pitivi video editor
#
#       pitivi/preset.py
#
# Copyright (c) 2010, Brandon Lewis <brandon_lewis@berkeley.edu>
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

import json
import os.path

from gi.repository import Gst
from gi.repository import Gtk

from gettext import gettext as _

from pitivi.settings import xdg_data_home
from pitivi.utils.misc import isWritable
from pitivi.configure import get_renderpresets_dir, get_audiopresets_dir, get_videopresets_dir
from pitivi.utils import system
from pitivi.utils.loggable import Loggable


class DuplicatePresetNameException(Exception):

    """Raised when an operation would result in a duplicated preset name."""
    pass


class PresetManager(Loggable):

    """Abstract class for storing a list of presets.

    Subclasses must provide a filename attribute.

    @cvar filename: The name of the file where the presets will be stored.
    @type filename: str

    @ivar cur_preset: The currently selected preset. Note that a preset has to
        be selected before it can be changed.
    @type cur_preset: str
    @ivar ordered: A list holding (name -> preset_dict) tuples.
    @type ordered: Gtk.ListStore
    @ivar presets: A (name -> preset_dict) map.
    @type presets: dict
    @ivar widget_map: A (propname -> (setter_func, getter_func)) map.
        These two functions are used when showing or saving a preset.
    @type widget_map: dict
    """

    def __init__(self, default_path, user_path):
        Loggable.__init__(self)

        self.default_path = default_path
        self.user_path = user_path

        self.presets = {}
        self.widget_map = {}
        self.ordered = Gtk.ListStore(str, object)
        self.cur_preset = None
        # Whether to ignore the updateValue calls.
        self.ignore_update_requests = False
        self.system = system.getSystem()

    def loadAll(self):
        self._loadFromDir(self.default_path)
        if os.path.isfile(self.user_path):
            # We used to save presets as a single file instead of a directory
            os.rename(self.user_path, "%s.old" % self.user_path)
        self._loadFromDir(self.user_path)

    def _loadFromDir(self, presets_dir):
        try:
            files = os.listdir(presets_dir)
        except FileNotFoundError:
            self.debug("Presets directory missing: %s", presets_dir)
            return
        for uri in files:
            filepath = os.path.join(presets_dir, uri)
            if filepath.endswith("json"):
                self._loadSection(filepath)

    def saveAll(self):
        """Write changes to disk for all presets"""
        for preset_name, values in self.ordered:
            self.savePreset(preset_name)

    def savePreset(self, preset_name):
        if not os.path.exists(self.user_path):
            os.makedirs(self.user_path)
        try:
            file_path = self.presets[preset_name]["filepath"]
        except KeyError:
            file_name = self.system.getUniqueFilename(preset_name + ".json")
            file_path = os.path.join(self.user_path, file_name)
            self.presets[preset_name]["filepath"] = file_path
        with open(file_path, "w") as fout:
            values = self.presets[preset_name]
            raw = self._serializePreset(values)
            raw["name"] = preset_name
            serialized = json.dumps(raw, indent=4)
            fout.write(serialized)

    def getUniqueName(self, first=_("Custom"), second=_("Custom %d")):
        name = first
        i = 1
        while self.hasPreset(name):
            name = second % i
            i += 1
        return name

    def getNewPresetName(self):
        """Get a unique name for a new preset."""
        return self.getUniqueName(_("New preset"), _("New preset %d"))

    def createPreset(self, name, values, volatile=False):
        """Create a new preset.

        @param name: The name of the new preset, must be unique.
        @type name: str
        @param values: The values of the new preset.
        @type values: dict
        @param volatile: Whether the preset should not be saveable.
        @type volatile: bool
        """
        if self.hasPreset(name):
            raise DuplicatePresetNameException(name)
        if volatile:
            values["volatile"] = True
        self._addPreset(name, values)

    def _addPreset(self, name, values):
        """Add a preset, overwriting the preset with the same name if it exists.

        @param name: The name of the new preset.
        @type name: str
        @param values: The values of the new preset.
        @type values: dict
        """
        if self.hasPreset(name):
            for i, row in enumerate(self.ordered):
                if row[0] == name:
                    del self.presets[row[1]["name"]]
                    del self.ordered[i]
                    break
        self.presets[name] = values
        # Note: This generates a "row-inserted" signal in the model.
        self.ordered.append((name, values))

    def renamePreset(self, path, new_name):
        """Change the name of a preset.

        @param path: The path in the model identifying the preset to be renamed.
        @type path: str
        @param new_name: The new name for the preset.
        @type new_name: str
        """
        old_name = self.ordered[path][0]
        assert old_name in self.presets
        if old_name == new_name:
            # Nothing to do.
            return
        if old_name.lower() != new_name.lower() and self.hasPreset(new_name):
            raise DuplicatePresetNameException()
        self.ordered[path][0] = new_name
        self.presets[new_name] = self.presets[old_name]
        if "filepath" in self.presets[old_name]:
            # If the previous preset had already been saved,
            # delete the file and pop it from the list
            self.removePreset(old_name)
        else:
            # We're renaming an unsaved preset, so just pop it from the list
            self.presets.pop(old_name)
        new_filepath = os.path.join(self.user_path, new_name + ".json")
        self.presets[new_name]["filepath"] = new_filepath
        self.cur_preset = new_name
        self.saveCurrentPreset()

    def hasPreset(self, name):
        name = name.lower()
        return any(name == preset.lower() for preset in self.getPresetNames())

    def getPresetNames(self):
        return (row[0] for row in self.ordered)

    def getModel(self):
        """Get the GtkModel used by the UI."""
        return self.ordered

    def updateValue(self, name, value):
        """Update a value in the current preset, if any."""
        if self.ignore_update_requests:
            # This is caused by restorePreset, nothing to do.
            return
        if self.cur_preset:
            self.presets[self.cur_preset][name] = value

    def bindWidget(self, propname, setter_func, getter_func):
        """Link the specified functions to the specified preset property."""
        self.widget_map[propname] = (setter_func, getter_func)

    def restorePreset(self, preset):
        """Select a preset and copy the values from the preset to the widgets.

        @param preset: The name of the preset to be selected.
        @type preset: str
        """
        if preset is None:
            self.cur_preset = None
            return
        if preset not in self.presets:
            return
        self.ignore_update_requests = True
        try:
            values = self.presets[preset]
            self.cur_preset = preset
            for field, (setter, getter) in self.widget_map.items():
                setter(values[field])
        finally:
            self.ignore_update_requests = False

    def saveCurrentPreset(self):
        """Update the current preset values from the widgets and save it."""
        self._updatePreset()
        self.savePreset(self.cur_preset)

    def _updatePreset(self):
        """Copy the values from the widgets to the preset."""
        values = self.presets[self.cur_preset]
        for field, (setter, getter) in self.widget_map.items():
            values[field] = getter()

    def _isCurrentPresetChanged(self):
        """Return whether the widgets values differ from those of the preset."""
        if not self.cur_preset:
            # There is no preset selected, nothing to do.
            return False
        values = self.presets[self.cur_preset]
        return any((values[field] != getter()
                    for field, (setter, getter) in self.widget_map.items()))

    def removePreset(self, name=None):
        if name is None:
            name = self.cur_preset
        try:
            # Deletes json file if exists
            os.remove(self.presets[name]["filepath"])
        except KeyError:
            # Trying to remove a preset that has not actually been saved
            return
        except Exception:
            raise
        self.presets.pop(name)
        for i, row in enumerate(self.ordered):
            if row[0] == name:
                del self.ordered[i]
                break
        if self.cur_preset == name:
            self.cur_preset = None

    def prependPreset(self, name, values):
        self.presets[name] = values
        # Note: This generates a "row-inserted" signal in the model.
        self.ordered.prepend((name, values))

    def isSaveButtonSensitive(self):
        """Whether the Save button should be enabled"""
        if not self.cur_preset:
            return False
        if "volatile" in self.presets[self.cur_preset]:
            return False
        try:
            full_path = self.presets[self.cur_preset]["filepath"]
        except KeyError:
            # This is a newly created preset that has not yet been saved
            return True
        (dir, name) = os.path.split(full_path)
        if dir == self.default_path or not isWritable(full_path):
            # default_path is the system-wide directory where the default
            # presets are installed; they are not expected to be editable.
            return False
        else:
            return self._isCurrentPresetChanged()

    def isRemoveButtonSensitive(self):
        """Whether the Remove button should be enabled"""
        if not self.cur_preset:
            return False
        if "volatile" in self.presets[self.cur_preset]:
            return False
        try:
            full_path = self.presets[self.cur_preset]["filepath"]
            (dir, name) = os.path.split(full_path)
        except KeyError:
            # This is a newly created preset that has not yet been saved
            # We cannot remove it since it does not exist
            return False
        if dir == self.default_path or not isWritable(full_path):
            # default_path is the system-wide directory where the default
            # presets are installed; they are not expected to be editable.
            return False
        return True

    def _objectToPreset(self, *args):
        raise NotImplementedError()

    def matchingPreset(self, *args):
        query = self._objectToPreset(*args)
        for name, preset in self.presets.items():
            matches = True
            for key, value in query.items():
                if not value == preset.get(key):
                    matches = False
                    break
            if matches:
                return name
        return None


class VideoPresetManager(PresetManager):

    def __init__(self):
        default_path = get_videopresets_dir()
        user_path = os.path.join(xdg_data_home(), 'video_presets')
        PresetManager.__init__(self, default_path, user_path)

    def _loadSection(self, filepath):
        with open(filepath) as section:
            parser = json.loads(section.read())

        name = parser["name"]
        width = parser["width"]
        height = parser["height"]

        framerate_num = parser["framerate-num"]
        framerate_denom = parser["framerate-denom"]
        framerate = Gst.Fraction(framerate_num, framerate_denom)

        par_num = parser["par-num"]
        par_denom = parser["par-denom"]
        par = Gst.Fraction(par_num, par_denom)

        self._addPreset(name, {
            "width": width,
            "height": height,
            "frame-rate": framerate,
            "par": par,
            "filepath": filepath,
        })

    def _serializePreset(self, preset):
        return {
            "width": int(preset["width"]),
            "height": int(preset["height"]),
            "framerate-num": preset["frame-rate"].num,
            "framerate-denom": preset["frame-rate"].denom,
            "par-num": preset["par"].num,
            "par-denom": preset["par"].denom,
        }

    def _objectToPreset(self, project):
        return {
            "width": project.videowidth,
            "height": project.videoheight,
            "frame-rate": project.videorate,
            "par": project.videopar}


class AudioPresetManager(PresetManager):

    def __init__(self):
        default_path = get_audiopresets_dir()
        user_path = os.path.join(xdg_data_home(), 'audio_presets')
        PresetManager.__init__(self, default_path, user_path)

    def _loadSection(self, filepath):
        with open(filepath) as section:
            parser = json.loads(section.read())

        name = parser["name"]
        channels = parser["channels"]
        sample_rate = parser["sample-rate"]

        self._addPreset(name, {
            "channels": channels,
            "sample-rate": sample_rate,
            "filepath": filepath,
        })

    def _serializePreset(self, preset):
        return {
            "channels": preset["channels"],
            "sample-rate": int(preset["sample-rate"]),
        }

    def _objectToPreset(self, project):
        return {
            "channels": project.audiochannels,
            "sample-rate": project.audiorate}


class RenderPresetManager(PresetManager):

    def __init__(self):
        default_path = get_renderpresets_dir()
        user_path = os.path.join(xdg_data_home(), 'render_presets')
        PresetManager.__init__(self, default_path, user_path)

    def _loadSection(self, filepath):
        with open(filepath) as section:
            parser = json.loads(section.read())

        name = parser["name"]
        container = parser["container"]
        acodec = parser["acodec"]
        vcodec = parser["vcodec"]

        from pitivi.render import CachedEncoderList
        cached_encs = CachedEncoderList()
        if (acodec not in [fact.get_name() for fact in cached_encs.aencoders] or
                vcodec not in [fact.get_name() for fact in cached_encs.vencoders] or
                container not in [fact.get_name() for fact in cached_encs.muxers]):
            return

        try:
            width = parser["width"]
            height = parser["height"]
        except:
            width = 0
            height = 0

        framerate_num = parser["framerate-num"]
        framerate_denom = parser["framerate-denom"]
        framerate = Gst.Fraction(framerate_num, framerate_denom)

        channels = parser["channels"]
        sample_rate = parser["sample-rate"]

        self._addPreset(name, {
            "container": container,
            "acodec": acodec,
            "vcodec": vcodec,
            "width": width,
            "height": height,
            "frame-rate": framerate,
            "channels": channels,
            "sample-rate": sample_rate,
            "filepath": filepath,
        })

    def _serializePreset(self, preset):
        return {
            "container": str(preset["container"]),
            "acodec": str(preset["acodec"]),
            "vcodec": str(preset["vcodec"]),
            "width": int(preset["width"]),
            "height": int(preset["height"]),
            "framerate-num": preset["frame-rate"].num,
            "framerate-denom": preset["frame-rate"].denom,
            "channels": preset["channels"],
            "sample-rate": int(preset["sample-rate"]),
        }
