# -*- coding: utf-8 -*-
# Pitivi Developer Console
# Copyright (c) 2017, Fabian Orccon <cfoch.fabian@gmail.com>
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
"""The developer console widget."""
import sys
from code import InteractiveConsole

from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import Gtk
from utils import FakeOut
from utils import swap_std


class ConsoleWidget(Gtk.ScrolledWindow):
    """An emulated Python console.

    The console can be used to access an app, window, or anything through the
    provided namespace. It works redirecting stdout and stderr to a
    GtkTextBuffer. This class is (and should be) independent of the application
    it is integrated with.
    """

    # pylint: disable=too-many-instance-attributes
    def __init__(self, namespace):
        Gtk.ScrolledWindow.__init__(self)
        self.__view = Gtk.TextView()

        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.__view.set_editable(True)
        self.__view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.add(self.__view)

        buf = self.__view.get_buffer()
        self._normal = buf.create_tag("normal")
        self._error = buf.create_tag("error")
        self._command = buf.create_tag("command")

        self._console = InteractiveConsole(namespace)

        # Init prompt and first line.
        sys.ps1 = ">>> "
        sys.ps2 = "... "
        buf.create_mark("input-line", buf.get_end_iter(), True)
        buf.insert(buf.get_end_iter(), sys.ps1)
        buf.create_mark("after-prompt", buf.get_end_iter(), True)

        # Init history.
        self.history = [""]
        self.history_pos = 0
        namespace["__history__"] = self.history

        # Set up hooks for standard output.
        self.__stdout = FakeOut(self, self._normal)
        self.__stderr = FakeOut(self, self._error)

        # Signals.
        self.__view.connect("key-press-event", self.__key_press_event_cb)
        buf.connect("mark-set", self.__mark_set_cb)

        # Prompt.
        self.prompt = sys.ps1

    def _process_command_line(self):
        # Get the marks.
        buf = self.__view.get_buffer()
        input_line_mark = buf.get_mark("input-line")
        after_prompt_mark = buf.get_mark("after-prompt")

        # Get the command line.
        after_prompt_iter = buf.get_iter_at_mark(after_prompt_mark)
        end_iter = buf.get_end_iter()
        line = buf.get_text(after_prompt_iter, end_iter, False)
        self.history_add(line)

        # Apply a color to the line.
        input_line_iter = buf.get_iter_at_mark(input_line_mark)
        buf.apply_tag(self._command, input_line_iter, end_iter)
        buf.insert(end_iter, "\n")

        with swap_std(self.__stdout, self.__stderr):
            is_command_incomplete = self._console.push(line)

        if not is_command_incomplete:
            # The command executed successfully.
            self.prompt = sys.ps1
        else:
            self.prompt = sys.ps2

        # Prepare the new line.
        end_iter = buf.get_end_iter()
        buf.move_mark(input_line_mark, end_iter)
        buf.insert(end_iter, self.prompt)
        end_iter = buf.get_end_iter()
        buf.move_mark(after_prompt_mark, end_iter)
        buf.place_cursor(end_iter)
        GLib.idle_add(self.scroll_to_end)
        return True

    def __is_cursor_at_start(self):
        """Returns whether the cursor is exactly after the prompt."""
        # pylint: disable=no-self-use
        buf = self.__view.get_buffer()
        after_prompt_iter = buf.get_iter_at_mark(buf.get_mark("after-prompt"))
        cursor_iter = buf.get_iter_at_mark(buf.get_insert())
        return after_prompt_iter.compare(cursor_iter) == 0

    def __key_press_event_cb(self, view, event):
        if event.keyval == Gdk.KEY_Return:
            return self._process_command_line()
        elif event.keyval == Gdk.KEY_KP_Down or event.keyval == Gdk.KEY_Down:
            return self.history_down()
        elif event.keyval == Gdk.KEY_KP_Up or event.keyval == Gdk.KEY_Up:
            return self.history_up()
        elif event.keyval == Gdk.KEY_KP_Left or event.keyval == Gdk.KEY_Left or \
                event.keyval == Gdk.KEY_BackSpace:
            return self.__is_cursor_at_start()

    def __mark_set_cb(self, buf, it, name):
        after_prompt_iter = buf.get_iter_at_mark(buf.get_mark("after-prompt"))
        pos_iter = buf.get_iter_at_mark(buf.get_insert())
        self.__view.set_editable(pos_iter.compare(after_prompt_iter) != -1)

    def get_command_line(self):
        """Gets the last command line after the prompt.

        A command line can be a single line or many lines for example when
        a function or a class is defined.
        """
        buf = self.__view.get_buffer()
        after_prompt_iter = buf.get_iter_at_mark(buf.get_mark("after-prompt"))
        end_iter = buf.get_end_iter()
        return buf.get_text(after_prompt_iter, end_iter, False)

    def set_command_line(self, command):
        """Inserts a command line after the prompt."""
        buf = self.__view.get_buffer()
        after_prompt_mark = buf.get_mark("after-prompt")
        after_prompt_iter = buf.get_iter_at_mark(after_prompt_mark)
        end_iter = buf.get_end_iter()
        buf.delete(after_prompt_iter, end_iter)
        buf.insert(after_prompt_iter, command)
        self.__view.grab_focus()

    def history_add(self, line):
        """Adds a command line to the history."""
        if line.strip():
            self.history_pos = len(self.history)
            if (self.history_pos >= 2 and
                    self.history[self.history_pos - 2] == line):
                self.history_pos = self.history_pos - 1
            else:
                self.history[self.history_pos - 1] = line
                self.history.append("")

    def history_up(self):
        """Sets the current command line with the previous used command line."""
        if self.history_pos > 0:
            self.history[self.history_pos] = self.get_command_line()
            self.history_pos = self.history_pos - 1
            self.set_command_line(self.history[self.history_pos])
            GLib.idle_add(self.scroll_to_end)
        return True

    def history_down(self):
        """Sets the current command line with the next available used command line."""
        if self.history_pos < len(self.history) - 1:
            self.history[self.history_pos] = self.get_command_line()
            self.history_pos = self.history_pos + 1
            self.set_command_line(self.history[self.history_pos])
            GLib.idle_add(self.scroll_to_end)
        return True

    def scroll_to_end(self):
        """Scrolls the view to the end."""
        end_iter = self.__view.get_buffer().get_end_iter()
        self.__view.scroll_to_iter(end_iter, 0.0, False, 0.5, 0.5)
        return False

    def write(self, text, tag=None):
        """Writes a text to the text view's buffer.

        If a tag is given, then the tags are applied to that buffer.
        """
        buf = self.__view.get_buffer()
        if tag is None:
            buf.insert(buf.get_end_iter(), text)
        else:
            buf.insert_with_tags(buf.get_end_iter(), text, tag)

        GLib.idle_add(self.scroll_to_end)
