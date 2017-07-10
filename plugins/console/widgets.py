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
import builtins
import os
import re
import sys
from code import InteractiveConsole
from keyword import kwlist

from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Pango
from utils import display_autocompletion
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
        self.normal = buf.create_tag("normal")
        self.error = buf.create_tag("error")
        self.command = buf.create_tag("command")

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
        self.__stdout = FakeOut(self, self.normal, sys.stdout.fileno())
        self.__stderr = FakeOut(self, self.error, sys.stdout.fileno())

        # Signals.
        self.__view.connect("key-press-event", self.__key_press_event_cb)
        buf.connect("mark-set", self.__mark_set_cb)
        buf.connect("insert-text", self.__insert_text_cb)

        # Prompt.
        self.prompt = sys.ps1

        self._provider = Gtk.CssProvider()
        self._css_values = {
            "textview": {
                "font-family": None,
                "font-size": None,
                "font-style": None,
                "font-variant": None,
                "font-weight": None
            },
            "textview > *": {
                "color": None
            }
        }

    def set_font(self, font_desc):
        """Sets the font.

        Args:
            font (str): a PangoFontDescription as a string.
        """
        pango_font_desc = Pango.FontDescription.from_string(font_desc)
        self._css_values["textview"]["font-family"] = pango_font_desc.get_family()
        self._css_values["textview"]["font-size"] = "%dpt" % int(pango_font_desc.get_size() / Pango.SCALE)
        self._css_values["textview"]["font-style"] = pango_font_desc.get_style().value_nick
        self._css_values["textview"]["font-variant"] = pango_font_desc.get_variant().value_nick
        self._css_values["textview"]["font-weight"] = int(pango_font_desc.get_weight())
        self._apply_css()
        self.error.set_property("font", font_desc)
        self.command.set_property("font", font_desc)
        self.normal.set_property("font", font_desc)

    def set_color(self, color):
        """Sets the color.

        Args:
            color (Gdk.RGBA): a color.
        """
        self._css_values["textview > *"]["color"] = color.to_string()
        self._apply_css()

    def _apply_css(self):
        css = ""
        for css_klass, props in self._css_values.items():
            css += "%s {" % css_klass
            for prop, value in props.items():
                if value is not None:
                    css += "%s: %s;" % (prop, value)
            css += "} "
        css = css.encode("UTF-8")
        self._provider.load_from_data(css)
        Gtk.StyleContext.add_provider(self.__view.get_style_context(),
                                      self._provider,
                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

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
        buf.apply_tag(self.command, input_line_iter, end_iter)
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

    def show_autocompletion(self, command):
        """Prints the autocompletion to the view."""
        matches, last, new_command = self.get_autocompletion_matches(command)
        namespace = {
            "last": last,
            "matches": matches,
            "buf": self.__view.get_buffer(),
            "command": command,
            "new_command": new_command,
            "display_autocompletion": display_autocompletion
        }
        with swap_std(self.__stdout, self.__stderr):
            # pylint: disable=eval-used
            eval("display_autocompletion(last, matches, buf, command, new_command)",
                 namespace, self._console.locals)
        if len(matches) > 1:
            self.__refresh_prompt(new_command)

    def get_autocompletion_matches(self, input_text):
        """
        Given an input text, return possible matches for autocompletion.
        """
        # pylint: disable=bare-except, eval-used, too-many-branches
        # Try to get the possible full object to scan.
        # For example, if input_text is "func(circle.ra", we obtain "circle.ra".
        identifiers = re.findall(r"[_A-Za-z][\w\.]*\w$", input_text)
        if identifiers:
            maybe_scannable_object = identifiers[0]
        else:
            maybe_scannable_object = input_text

        pos = maybe_scannable_object.rfind(".")
        if pos != -1:
            # In this case, we cannot scan "circle.ra", so we scan "circle".
            scannable_object = maybe_scannable_object[:pos]
        else:
            # This is the case when input was more simple, like "circ".
            scannable_object = maybe_scannable_object
        namespace = {"scannable_object": scannable_object}
        try:
            if pos != -1:
                str_eval = "dir(eval(scannable_object))"
            else:
                str_eval = "dir()"
            maybe_matches = eval(str_eval, namespace, self._console.locals)
        except:
            return [], maybe_scannable_object, input_text
        if pos != -1:
            # Get substring after last dot (.)
            rest = maybe_scannable_object[(pos + 1):]
        else:
            rest = scannable_object
        # First, assume we are parsing an object.
        matches = [match for match in maybe_matches if match.startswith(rest)]

        # If not matches, maybe it is a keyword or builtin function.
        if not matches:
            tmp_matches = kwlist + dir(builtins)
            matches = [
                match for match in tmp_matches if match.startswith(rest)]

        if not matches:
            new_input_text = input_text
        else:
            maybe_scannable_pos = input_text.find(maybe_scannable_object)
            common = os.path.commonprefix(matches)
            if pos == -1:
                new_input_text = input_text[:maybe_scannable_pos] + common
            else:
                new_input_text = input_text[:maybe_scannable_pos] + maybe_scannable_object[:pos] + "." + common

        return matches, rest, new_input_text

    def __refresh_prompt(self, text=""):
        buf = self.__view.get_buffer()

        # Get the marks
        input_line_mark = buf.get_mark("input-line")
        after_prompt_mark = buf.get_mark("after-prompt")

        # Prepare the new line
        end_iter = buf.get_end_iter()
        buf.move_mark(input_line_mark, end_iter)
        buf.insert(end_iter, self.prompt)
        end_iter = buf.get_end_iter()
        buf.move_mark(after_prompt_mark, end_iter)
        buf.place_cursor(end_iter)
        self.write(text)

        GLib.idle_add(self.scroll_to_end)
        return True

    def __mark_set_cb(self, buf, it, name):
        after_prompt_iter = buf.get_iter_at_mark(buf.get_mark("after-prompt"))
        pos_iter = buf.get_iter_at_mark(buf.get_insert())
        self.__view.set_editable(pos_iter.compare(after_prompt_iter) != -1)

    def __insert_text_cb(self, buf, it, text, user_data):
        command = self.get_command_line()
        if text == "\t" and not command.isspace():
            # If input text is '\t' and command doesn't start with spaces or tab
            # prevent GtkTextView to insert the text "\t" for autocompletion.
            GObject.signal_stop_emission_by_name(buf, "insert-text")
            self.show_autocompletion(command)

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
