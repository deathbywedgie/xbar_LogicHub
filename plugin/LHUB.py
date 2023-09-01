#!/usr/bin/env PYTHONIOENCODING=UTF-8 python3

# <xbar.title>LogicHub Utils: Stuff Chad Wanted (because OCD sucks)</xbar.title>
# <xbar.version>v3.0</xbar.version>
# <xbar.author>Chad Roberts</xbar.author>
# <xbar.author.github>deathbywedgie</xbar.author.github>
# <xbar.desc>Various helpful actions for LogicHub engineers and users</xbar.desc>
# <xbar.image></xbar.image>
# <xbar.dependencies>See readme.md</xbar.dependencies>
# <xbar.abouturl>https://github.com/deathbywedgie/BitBar_LogicHub</xbar.abouturl>

import base64
import configobj
import os
import re
import sqlparse
import sys
from dataclasses import dataclass
from dataclasses_json import dataclass_json
import traceback

import clipboard
import collections.abc
import psutil
import tempfile
from datetime import datetime
import argparse
from typing import Dict

# Global static variables
user_config_file = "xbar_logichub.ini"

# Will be updated if enabled via the config file
debug_enabled = False


def get_args():
    # Range of available args and expected input
    parser = argparse.ArgumentParser(description="LogicHub xbar plugin")

    # Inputs expected from user
    parser.add_argument("action", nargs='?', type=str, help="Name of an action to execute")

    # Optional args:
    parser.add_argument("-l", "--list", dest="list_actions", action="store_true", help="List available actions")

    # take in the arguments provided by user
    return parser.parse_args()


class Log:
    """
    Simple class for debug logging for the time being. May eventually replace with a real Logger
    """

    @property
    def debug_enabled(self):
        return debug_enabled

    def debug(self, msg):
        if self.debug_enabled:
            print(f"[DEBUG] {msg}")


class Reusable:
    # Class for static reusable methods, mainly just to group these together to better organize for readability

    @staticmethod
    def convert_boolean(_var):
        if type(_var) is str:
            _var2 = _var.strip().lower()
            if _var2 in ["yes", "true"]:
                return True
            elif _var2 in ["no", "false"]:
                return False
        return _var

    @staticmethod
    def dict_merge(*args, add_keys=True):
        """
        Deep (recursive) merge for dicts, because dict.update() only merges
        top-level keys. This version makes a copy of the original dict so that the
        original remains unmodified.

        The optional argument ``add_keys``, determines whether keys which are
        present in ``merge_dict`` but not ``dct`` should be included in the
        new dict. It also merges list entries instead of overwriting with a new list.
        """
        assert len(args) >= 2, "dict_merge requires at least two dicts to merge"
        rtn_dct = args[0].copy()
        merge_dicts = args[1:]
        for merge_dct in merge_dicts:
            if add_keys is False:
                merge_dct = {key: merge_dct[key] for key in set(rtn_dct).intersection(set(merge_dct))}
            for k, v in merge_dct.items():
                if not rtn_dct.get(k):
                    rtn_dct[k] = v
                elif v is None:
                    pass
                elif k in rtn_dct and not isinstance(v, type(rtn_dct[k])):
                    raise TypeError(
                        f"Overlapping keys exist with different types: original is {type(rtn_dct[k]).__name__}, new value is {type(v).__name__}")
                elif isinstance(rtn_dct[k], dict) and isinstance(merge_dct[k], collections.abc.Mapping):
                    rtn_dct[k] = Reusable.dict_merge(rtn_dct[k], merge_dct[k], add_keys=add_keys)
                elif isinstance(v, list):
                    for list_value in v:
                        if list_value not in rtn_dct[k]:
                            rtn_dct[k].append(list_value)
                else:
                    rtn_dct[k] = v
        return rtn_dct

    @staticmethod
    def generate_temp_file_path(file_ext, prefix=None, name_only=False):
        assert file_ext
        if prefix and not prefix.endswith("_"):
            prefix = prefix + "_"
        _temp_file_name = "{}{}".format(prefix or "", datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S-%f')[:-3])
        if file_ext:
            _temp_file_name += "." + file_ext
        if name_only:
            return _temp_file_name
        return os.path.join(tempfile.gettempdir(), _temp_file_name)

    @staticmethod
    def sort_dict_by_values(_input_str, reverse=False):
        # return sorted(_input_str.items(), key=lambda x: x[1], reverse=reverse)
        return {k: v for k, v in sorted(_input_str.items(), key=lambda x: x[1], reverse=reverse)}


# ToDo REVISIT

# ToDo Finish building the Icons class and switch everything over to using it
# ToDo Finish putting lh_batch_success.png to use for the "runtimeStats" section

class Icons:
    # Class for centralizing all logos used by the plugin

    file_menu_logichub = "LH_menu_logichub.ico"
    file_menu_ssh = "LH_menu_ssh.png"

    file_status_small = "LH_menu_status_small.png"
    file_status_large = "LH_menu_status_large.png"
    file_status_large_dark = "LH_menu_status_large_dark.png"
    file_status_xlarge = "LH_menu_status_xlarge.png"
    file_status_xlarge_dark = "LH_menu_status_xlarge_dark.png"

    file_lh_batch_success = "lh_batch_success.png"

    def __init__(self, repo_path):
        self.image_path = os.path.join(repo_path, "supporting_files/images")


@dataclass_json
@dataclass
class ConfigMain:
    # Path to the code repo. No default here, as this is a required field.
    repo_path: str

    # Local user ID. If not provided, user will be drawn from USER environment variable
    local_user: str

    # Default SSH username. If not provided, user will be drawn from USER environment variable
    ssh_user: str

    # SSH keys are assumed to be located in ~/.ssh unless a full path is provided
    ssh_key: str

    # Return either "Dark" or "Light" for the OS theme
    os_theme: str

    # Usually "lo0"
    default_loopback_interface: str

    # Define how this plugin should appear in the status bar
    # Options: logo, text, both, custom
    status_bar_style: str

    # Text for the notification label (not used if status_bar_style is set to logo)
    # Default is "<PROJECT_NAME>"
    # If status_bar_style is set to "custom", you can specify additional formatting criteria according to xbar's plugin API
    status_bar_label: str

    # Choose the logo: small, large, xl
    status_bar_icon_size: str

    # Override the color of the text in the status bar (ignored if text is disabled by the selected style)
    status_bar_text_color: str

    # Generate a popup notification every time the clipboard gets updated
    clipboard_update_notifications: bool

    # Show debug output
    debug_output_enabled: bool

    # default Jira prefix (project name)
    jira_default_prefix: str


@dataclass_json
@dataclass
class ConfigMenuNetworking:
    configs: dict


# ToDo Finish this new feature
@dataclass_json
@dataclass
class ConfigMenuCustom:
    def __post_init__(self):
        pass


@dataclass_json
@dataclass
class Config:
    main: ConfigMain = None
    menu_custom: ConfigMenuCustom = None
    menu_networking: ConfigMenuNetworking = None

    def __post_init__(self):
        config_sections = ["main", "menu_networking", "menu_custom"]

        # initialize a config obj for the user's ini config file
        self.user_settings_dict = configobj.ConfigObj(os.path.join(os.environ.get("HOME"), user_config_file))
        if not self.user_settings_dict:
            print(f"{user_config_file} not found")
            sys.exit(1)
        else:
            for k in config_sections:
                if k not in self.user_settings_dict:
                    self.user_settings_dict[k] = {}

        self.get_config_main(**self.user_settings_dict.get("main", {}))
        if self.main.debug_output_enabled:
            global debug_enabled
            debug_enabled = self.main.debug_output_enabled

        if not self.main.repo_path:
            print(f"repo_path not set in {user_config_file}")
            sys.exit(1)

        self.get_config_menu_networking_params(**self.user_settings_dict.get("menu_networking", {}))
        self.menu_custom = ConfigMenuCustom()

        # Find the path to the home directory
        self.dir_user_home = os.environ.get("HOME")

        self.default_loopback_interface = self.main.default_loopback_interface
        self.local_user = self.main.local_user
        self.default_ssh_key = self.main.ssh_key
        if "/" not in self.default_ssh_key:
            self.default_ssh_key = os.path.join(self.dir_user_home, ".ssh", self.default_ssh_key)

        self.dir_internal_tools = self.main.repo_path
        self.dir_supporting_scripts = os.path.join(self.dir_internal_tools, "scripts")
        self.image_file_path = os.path.join(self.dir_internal_tools, 'supporting_files/images')

        logos_by_os_theme = {
            "Dark": {
                "small": "LH_menu_status_small.png",
                "large": "LH_menu_status_large_dark.png",
                "xl": "LH_menu_status_xlarge_dark.png",
            },
            "Light": {
                "small": "LH_menu_status_small.png",
                "large": "LH_menu_status_large.png",
                "xl": "LH_menu_status_xlarge.png",
            }
        }
        self.status_bar_logo = logos_by_os_theme[self.main.os_theme][self.main.status_bar_icon_size]

    def get_config_main(self, **kwargs):
        self.main = ConfigMain(
            repo_path=kwargs.get("repo_path", None),
            local_user=kwargs.get("local_user", os.environ.get("USER")),
            ssh_user=kwargs.get("ssh_user", os.environ.get("USER")),
            ssh_key=kwargs.get("ssh_key", "id_rsa"),
            os_theme=kwargs.get("os_theme", os.popen(
                'defaults read -g AppleInterfaceStyle 2> /dev/null').read().strip() or "Light"),
            default_loopback_interface=kwargs.get("default_loopback_interface", "lo0"),
            status_bar_style=kwargs.get("status_bar_style", "logo"),
            status_bar_label=kwargs.get("status_bar_label", "LHUB"),
            status_bar_icon_size=kwargs.get("status_bar_icon_size", "large"),
            status_bar_text_color=kwargs.get("status_bar_text_color", "black"),
            clipboard_update_notifications=Reusable.convert_boolean(
                kwargs.get("clipboard_update_notifications", False)),
            debug_output_enabled=Reusable.convert_boolean(kwargs.get("debug_output_enabled", False)),
            jira_default_prefix=kwargs.get("jira_default_prefix", "<PROJECT_NAME>")
        )

    def get_config_menu_networking_params(self, **kwargs):
        self.menu_networking = ConfigMenuNetworking(kwargs)


@dataclass
class ActionObject:
    id: str
    name: str
    action: classmethod


class Actions:
    # Static items
    loopback_interface = None

    # Defaults
    ssh_tunnel_configs = []
    port_redirect_configs = []
    __reserved_keyboard_shortcuts = {}

    def __init__(self, config):
        me = psutil.Process()
        parent = psutil.Process(me.ppid())
        self.parent = parent.name()
        self.menu_type = self.parent if self.parent in ('BitBar', 'xbar') else 'pystray'

        self.title_default = "LogicHub Helpers"
        self.script_name = os.path.abspath(sys.argv[0])
        self.status = ""
        self.menu_output = ""

        # ToDo FIX THIS: Hostname should be passed through the ini file
        self.url_jira = r"https://projet.atlassian.net/browse/{}"
        self.url_uws = r"https://www.ultimatewindowssecurity.com/securitylog/encyclopedia/event.aspx?eventID={}"
        self.url_nmap = r"https://nmap.org/nsedoc/scripts/{}"

        self.config = config

        self.set_status_bar_display()
        self.loopback_interface = self.config.default_loopback_interface

        # dict to store all the actions
        self.action_list: Dict[str, ActionObject] = {}

        # ToDo Move all of these to main so it's easier to find going forward!

        # ------------ Menu Section: LogicHub ------------ #

        self.add_menu_section(
            "LogicHub | image={} size=20 color=blue".format(self.image_to_base64_string("LH_menu_logichub.ico")))
        self.print_in_menu("LQL: SQL & Web UI")

        # ------------ Menu Sub-section: LQL: SQL and Web UI ------------ #

        self.add_menu_section("SQL", text_color="blue", menu_depth=1)

        # ToDo Add section for common SQL
        #   LQL to convert XML to JSON: java_method('org.json.XML', 'toJSONObject', test_xml)
        #   Case management custom fields

        self.make_action("Pretty Print SQL", self.sql_pretty_print)
        self.make_action("Pretty Print SQL options", action=None, alternate=True)
        self.make_action("Wrapped at 80 characters", self.sql_pretty_print_sql, menu_depth=2)
        self.make_action("Compact", self.sql_pretty_print_compact, menu_depth=2)

        self.make_action("Tabs to commas", self.spaced_string_to_commas)
        self.make_action("Tabs to commas (force lowercase)", self.spaced_string_to_commas_lowercase, alternate=True)

        self.make_action("Tabs to commas (sorted)", self.spaced_string_to_commas_sorted)
        self.make_action("Tabs to commas (sorted, force lowercase)", self.spaced_string_to_commas_sorted_lowercase,
                         alternate=True)

        self.make_action("Tabs to commas & quotes", self.spaced_string_to_commas_and_quotes)
        self.make_action("Tabs to commas & quotes (force lowercase)",
                         self.spaced_string_to_commas_and_quotes_lowercase, alternate=True)

        self.make_action("Tabs to commas & quotes (sorted)", self.spaced_string_to_commas_and_quotes_sorted)
        self.make_action("Tabs to commas & quotes (sorted, force lowercase)",
                         self.spaced_string_to_commas_and_quotes_sorted_lowercase, alternate=True)

        self.make_action("SQL Start from spaced strings", self.sql_start_from_tabs)
        self.make_action("SQL Start from spaced strings (sorted)", self.sql_start_from_tabs_sorted)
        self.make_action("SQL Start from spaced strings (distinct)", self.sql_start_from_tabs_distinct)

        self.make_action("SQL Start from spaced strings (join with left columns)",
                         self.sql_start_from_tabs_join_left)
        self.make_action("SQL Start from spaced strings (join, left columns only)",
                         self.sql_start_from_tabs_join_left_columns_only, alternate=True)

        self.make_action("SQL Start from spaced strings (join with right columns)",
                         self.sql_start_from_tabs_join_right)
        self.make_action("SQL Start from spaced strings (join, right columns only)",
                         self.sql_start_from_tabs_join_right_columns_only, alternate=True)

    def add_menu_section(self, label, menu_depth=0, text_color=None):
        """
        Print a divider line as needed by the plugin menu, then print a label for the new section
        :param label:
        :param menu_depth: 0 for top level, 1 for submenu, 2 for first nested submenu, etc.
        :param text_color:
        :return:
        """
        assert label, "New menu section requested without providing a label"
        if text_color and ' color=' not in label:
            label += f"| color={text_color}"
        self.add_menu_divider_line(menu_depth=menu_depth)
        self.print_in_menu("--" * menu_depth + label)

    def add_menu_divider_line(self, menu_depth=0):
        """
        Print a divider line in the plugin menu
        Menu depth of 0 for top level menu, 1 for first level submenu, 2 for a nested submenu, etc.
        :param menu_depth:
        :return:
        """
        _divider_line = "---" + "--" * menu_depth
        self.print_in_menu(_divider_line)

    def print_menu_output(self):
        print(self.menu_output.strip())

    ############################################################################
    # Reusable functions
    ############################################################################
    def display_notification(self, content, title=None):
        content = content.replace('"', '\\"')
        if not title:
            title = self.title_default
        # subprocess.call(["osascript", "-e", f'display notification "{content}" with title "{title}"'])
        _output = os.popen(f'osascript -e "display notification \\"{content}\\" with title \\"{title}\\""')

    def display_notification_error(self, content, title=None, print_stderr=False, error_prefix="Failed with error: "):
        if '"' in content:
            # self.display_notification_error("Error returned, but the error message contained a quotation mark, which is not allowed by xbar")
            content = content.replace('"', "'")
        error_prefix = error_prefix if error_prefix and isinstance(error_prefix, str) else ""
        _output = os.popen('osascript -e "beep"')
        _error = f"{error_prefix}{content}"
        if print_stderr:
            print(f"\n{_error}\n")
        self.display_notification(_error, title)
        sys.exit(1)

    def print_in_menu(self, msg):
        self.menu_output += f"{msg}\n"

    def fail_action_with_exception(
            self, trace: traceback.format_exc = None,
            exception: BaseException = None, print_stderr=False):
        if not trace:
            trace = traceback.format_exc()
        self.write_clipboard(trace, skip_notification=True)
        error_msg = "Failed with an exception"
        if exception and isinstance(exception, BaseException):
            error_msg += f" ({type(exception).__name__})"
        error_msg += ": check traceback in clipboard"
        if exception:
            error_msg = f"Failed with an exception ({type(exception).__name__}): check traceback in clipboard"
        self.display_notification_error(error_msg, error_prefix="", print_stderr=print_stderr)

    def image_to_base64_string(self, file_name):
        file_path = os.path.join(self.config.image_file_path, file_name)
        with open(file_path, "rb") as image_file:
            image_bytes = image_file.read()
            image_b64 = base64.b64encode(image_bytes)
        return image_b64.decode("unicode_escape")

    def set_status_bar_display(self):
        # Ignore status_bar_label is status_bar_style is only the logo
        status_bar_label = "" if self.config.main.status_bar_style == "logo" else self.config.main.status_bar_label
        # If the status bar style is "custom," then whatever is passed in status_bar_label is the final product
        if self.config.main.status_bar_style != "custom":
            status_bar_label += "|"
            if self.config.main.status_bar_style in ["logo", "both"]:
                logo = self.image_to_base64_string(self.config.status_bar_logo)
                status_bar_label += f" image={logo}"
            if self.config.main.status_bar_style in ["text", "both"]:
                status_bar_label += f" color={self.config.main.status_bar_text_color}"
        self.status = status_bar_label

        # Set status bar text and/or logo
        self.print_in_menu(self.status)

    def make_action(
            self, name, action, action_id=None, menu_depth=1, alternate=False,
            terminal=False, text_color=None, keyboard_shortcut="", shell=None):
        menu_line = name
        if menu_depth:
            menu_line = '--' * menu_depth + ' ' + menu_line
        action_string = ''
        if alternate:
            action_string = action_string + ' alternate=true'
        if keyboard_shortcut:
            if keyboard_shortcut in self.__reserved_keyboard_shortcuts:
                raise ValueError(
                    f'Keyboard shortcut "{keyboard_shortcut}" already assigned to action "{self.__reserved_keyboard_shortcuts[keyboard_shortcut]}" and cannot be mapped to action {name}')
            self.__reserved_keyboard_shortcuts[keyboard_shortcut] = name
            action_string += ' | key=' + keyboard_shortcut
        menu_line += f' | {action_string}'
        if not action:
            if text_color:
                menu_line += f' color={text_color}'
            self.print_in_menu(menu_line)
            return

        if not action_id:
            action_id = re.sub(r'\W', "_", name)

        action_obj = ActionObject(id=action_id, name=name, action=action)
        self.action_list[action_id] = action_obj
        terminal = str(terminal).lower()
        menu_line += f' | bash="{self.script_name}" | param1="{action_id}" | terminal={terminal}'
        if shell:
            menu_line += f' | shell={shell}'
        self.print_in_menu(menu_line)
        return action_obj

    @staticmethod
    def read_clipboard(trim_input=True, lower=False, upper=False, strip_carriage_returns=True) -> str:
        if lower and upper:
            raise ValueError(
                "The \"lower\" and \"upper\" parameters in Actions.read_clipboard are mutually exclusive. Use one or the other, not both.")
        _input_str = clipboard.paste()
        if trim_input:
            _input_str = _input_str.strip()
        if lower is True:
            _input_str = _input_str.lower()
        if upper is True:
            _input_str = _input_str.upper()
        if strip_carriage_returns:
            # strip return characters (Windows formatting)
            _input_str = re.sub(r'\r', '', _input_str)
        return _input_str

    def write_clipboard(self, text, skip_notification=False):
        clipboard.copy(text)
        if self.config.main.clipboard_update_notifications and not skip_notification:
            self.display_notification("Clipboard updated")

    def copy_file_contents_to_clipboard(self, file_path, file_name=None):
        """
        Standardized method for reading a file and copying its contents to the
        clipboard. If only a file_path is passed, assume that it is a full path
        to a file. If file_name is provided, assume file_path is its location,
        and join them automatically before reading the file's contents.

        :param file_path: Location of the file to read
        :param file_name: (optional) Name of the file. If a value is provided,
        file_path will be assumed to be a directory and joined with file_name,
        otherwise file_path will be treated as a full path to a file.
        :return:
        """
        if file_name.strip():
            file_path = os.path.join(file_path, file_name)
        if not os.path.isfile(file_path):
            self.display_notification_error("Invalid path to supporting script")
        with open(file_path, "rU") as f:
            output = f.read()
        self.write_clipboard(output)

    def make_pretty_print_sql(self, input_str, wrap_after=0):
        """
        Reusable method to "pretty print" SQL

        :param input_str:
        :param wrap_after:
        :return:
        """
        try:
            # Replace line breaks with spaces, then trim leading and trailing whitespace
            _output = re.sub(r'[\n\r]+', ' ', input_str).strip()

            _output = sqlparse.format(
                _output, reindent=True, keyword_case='upper', indent_width=4,
                wrap_after=wrap_after, identifier_case=None)

            # nit: if just selecting "*" then drop that initial newline. no reason to drop "FROM" to the next row.
            if re.match(r"^SELECT \*\nFROM ", _output):
                _output = re.sub(r"^SELECT \*\n", "SELECT * ", _output)

            # specific keyword replacements for forcing uppercase
            specific_functions_to_uppercase = [
                "get_json_object", "from_unixtime", "min(", "max(", "sum(",
                "count(", "coalesce(", "regexp_replace", "regexp_extract("
            ]
            for f in specific_functions_to_uppercase:
                if f in _output:
                    _output = _output.replace(f, f.upper())

            # Workaround for "result" and other fields always getting turned into uppercase by sqlparse
            override_caps = ["result", "temp", "version", "usage", "instance"]
            for cap_field in override_caps:
                if re.findall(fr"\b{cap_field.upper()}\b", _output) and not re.findall(fr"\b{cap_field.upper()}\b",
                                                                                       input_str):
                    _output = re.sub(fr"\b{cap_field.upper()}\b", cap_field.lower(), _output)

            # Workaround to space out math operations
            _output = re.sub(r'\b([-+*/])(\d)', " \1 \2", _output)
        except Exception as err:
            self.display_notification_error("Exception from sqlparse: {}".format(repr(err)))
        else:
            return _output

    ############################################################################
    # Section:
    #   LogicHub
    ############################################################################

    def sql_pretty_print(self, **kwargs):
        """
        Pretty Print SQL

        :return:
        """
        _input_str = self.read_clipboard()
        _output = self.make_pretty_print_sql(_input_str, **kwargs)
        self.write_clipboard(_output)

    def sql_pretty_print_sql(self):
        """
        Pretty Print SQL: Wrapped at 80 characters

        :return:
        """
        self.sql_pretty_print(wrap_after=80)

    def sql_pretty_print_compact(self):
        """
        Pretty Print SQL: Compact

        :return:
        """
        self.sql_pretty_print(wrap_after=99999)

    def _split_spaced_string(self, force_lower=False, sort=False, quote=False, update_clipboard=True):
        _input_str = self.read_clipboard()

        # Remove commas and quotes in case the user clicked the wrong xbar option and wants to go right back to processing it
        # Remove pipes too so this can be used on postgresql headers as well
        _input_str = re.sub('[,"|\']+', ' ', _input_str)

        if force_lower:
            _input_str = _input_str.lower()
        _columns = [i.strip() for i in _input_str.split() if i.strip()]
        if sort:
            _columns = sorted(_columns)
        output_pattern = '"{}"' if quote else "{}"
        join_pattern = '", "' if quote else ", "
        final_output = output_pattern.format(join_pattern.join(_columns))
        if update_clipboard:
            self.write_clipboard(final_output)
        else:
            return final_output

    def spaced_string_to_commas(self):
        self._split_spaced_string()

    def spaced_string_to_commas_lowercase(self):
        self._split_spaced_string(force_lower=True)

    def spaced_string_to_commas_sorted(self):
        self._split_spaced_string(sort=True)

    def spaced_string_to_commas_sorted_lowercase(self):
        self._split_spaced_string(force_lower=True, sort=True)

    def spaced_string_to_commas_and_quotes(self):
        self._split_spaced_string(quote=True)

    def spaced_string_to_commas_and_quotes_lowercase(self):
        self._split_spaced_string(quote=True, force_lower=True)

    def spaced_string_to_commas_and_quotes_sorted(self):
        self._split_spaced_string(quote=True, sort=True)

    def spaced_string_to_commas_and_quotes_sorted_lowercase(self):
        self._split_spaced_string(quote=True, sort=True, force_lower=True)

    def sql_start_from_tabs(self):
        _columns_formatted = self._split_spaced_string(update_clipboard=False)
        self.write_clipboard(f'SELECT {_columns_formatted}\nFROM ')

    def sql_start_from_tabs_sorted(self):
        _columns_formatted = self._split_spaced_string(update_clipboard=False, sort=True)
        self.write_clipboard(f'SELECT {_columns_formatted}\nFROM ')

    def sql_start_from_tabs_distinct(self):
        _columns_formatted = self._split_spaced_string(update_clipboard=False)
        self.write_clipboard(f'SELECT DISTINCT {_columns_formatted}\nFROM ')

    def sql_start_from_tabs_join_left_columns_only(self):
        _input_str = self._split_spaced_string(update_clipboard=False)
        _columns = re.split(', *', _input_str)
        self.write_clipboard("L.{}".format(", L.".join(_columns)))

    def sql_start_from_tabs_join_right_columns_only(self):
        _input_str = self._split_spaced_string(update_clipboard=False)
        _columns = re.split(', *', _input_str)
        self.write_clipboard("R.{}".format(", R.".join(_columns)))

    def sql_start_from_tabs_join_left(self):
        _input_str = self._split_spaced_string(update_clipboard=False)
        _columns = re.split(', *', _input_str)
        _columns_formatted = "L.{}".format(", L.".join(_columns))
        self.write_clipboard(f'SELECT {_columns_formatted}\nFROM xxxx L\nLEFT JOIN xxxx R\nON L.xxxx = R.xxxx')

    def sql_start_from_tabs_join_right(self):
        _input_str = self._split_spaced_string(update_clipboard=False)
        _columns = re.split(', *', _input_str)
        _columns_formatted = "R.{}".format(", R.".join(_columns))
        self.write_clipboard(f'SELECT {_columns_formatted}\nFROM xxxx L\nLEFT JOIN xxxx R\nON L.xxxx = R.xxxx')

    def execute_plugin(self, action):
        log.debug(f"Executing action: {action}")
        if not action:
            self.print_menu_output()
            return
        # Not required, but helps with testing to be able to paste in the
        # original name of an action rather than have to know what the sanitized
        # action name ends up being
        action = re.sub(r'\W', "_", action)
        if action not in self.action_list:
            raise Exception("Not a valid action")
        else:
            try:
                self.action_list[action].action()
            except Exception as err:
                # self.fail_action_with_exception(traceback.format_exc())
                self.fail_action_with_exception(exception=err)


log = Log()


def main():
    args = get_args()
    config = Config()
    bar = Actions(config)

    if args.list_actions:
        for a in sorted(bar.action_list.keys()):
            """
            service_container_data: {"id": "service_container_data", "name": "service container data", "action": "<bound method Actions.shell_lh_host_path_to_service_container_volume of <__main__.Actions object at 0x1067aae50>>"}
            """
            action_path = re.findall(r"Actions.\S+", str(bar.action_list[a].action))[0]
            print(f'{bar.action_list[a].name}:\n\tID: {bar.action_list[a].id}\n\tAction: {action_path}\n')
        exit(0)

    bar.execute_plugin(args.action)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nControl-C Pressed; stopping...")
        exit(1)
