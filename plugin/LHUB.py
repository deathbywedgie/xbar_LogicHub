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
import json
import os
import re
import sqlparse
import subprocess
import shlex
import sys
from dataclasses import dataclass
from dataclasses_json import dataclass_json
import traceback
from numbers import Number

import clipboard
import collections.abc
import psutil
import tempfile
from datetime import datetime
import csv
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

    # Return either "Dark" or "Light" for the OS theme
    os_theme: str

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


@dataclass_json
@dataclass
class Config:
    main: ConfigMain = None

    def __post_init__(self):
        config_sections = ["main"]

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

        # Find the path to the home directory
        self.dir_user_home = os.environ.get("HOME")

        self.local_user = self.main.local_user

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
            os_theme=kwargs.get("os_theme", os.popen(
                'defaults read -g AppleInterfaceStyle 2> /dev/null').read().strip() or "Light"),
            status_bar_style=kwargs.get("status_bar_style", "logo"),
            status_bar_label=kwargs.get("status_bar_label", "LHUB"),
            status_bar_icon_size=kwargs.get("status_bar_icon_size", "large"),
            status_bar_text_color=kwargs.get("status_bar_text_color", "black"),
            clipboard_update_notifications=Reusable.convert_boolean(
                kwargs.get("clipboard_update_notifications", False)),
            debug_output_enabled=Reusable.convert_boolean(kwargs.get("debug_output_enabled", False))
        )


@dataclass
class ActionObject:
    id: str
    name: str
    action: classmethod


class Actions:
    # Defaults
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

        self.config = config

        self.set_status_bar_display()

        # dict to store all the actions
        self.action_list: Dict[str, ActionObject] = {}

        # ------------ Menu Section: LogicHub ------------ #

        self.add_menu_section(
            "LogicHub | image={} size=20 color=blue".format(self.image_to_base64_string("LH_menu_logichub.ico")))
        self.print_in_menu("LQL: SQL & Web UI")

        # ------------ Menu Sub-section: LQL: SQL and Web UI ------------ #

        self.add_menu_section("SQL", text_color="blue", menu_depth=1)

        # ToDo Add section for common SQL
        #   LQL to convert XML to JSON: java_method('org.json.XML', 'toJSONObject', test_xml)
        #   Case management custom fields

        self.make_action("Pretty Print SQL", self.logichub_pretty_print_sql, keyboard_shortcut="CmdOrCtrl+shift+p")
        self.make_action("Pretty Print SQL options", action=None, alternate=True)
        self.make_action("Wrapped at 80 characters", self.logichub_pretty_print_sql_wrapped, menu_depth=2)
        self.make_action("Compact", self.logichub_pretty_print_sql_compact, menu_depth=2)

        self.make_action("Tabs to commas", self.logichub_tabs_to_columns, keyboard_shortcut="CmdOrCtrl+shift+t")
        self.make_action("Tabs to commas (force lowercase)", self.logichub_tabs_to_columns_lowercase, alternate=True)

        self.make_action("Tabs to commas (sorted)", self.logichub_tabs_to_columns_sorted)
        self.make_action("Tabs to commas (sorted, force lowercase)", self.logichub_tabs_to_columns_sorted_lowercase,
                         alternate=True)

        self.make_action("Tabs to commas & quotes", self.logichub_tabs_to_columns_and_quotes)
        self.make_action("Tabs to commas & quotes (force lowercase)",
                         self.logichub_tabs_to_columns_and_quotes_lowercase, alternate=True)

        self.make_action("Tabs to commas & quotes (sorted)", self.logichub_tabs_to_columns_and_quotes_sorted)
        self.make_action("Tabs to commas & quotes (sorted, force lowercase)",
                         self.logichub_tabs_to_columns_and_quotes_sorted_lowercase, alternate=True)

        self.make_action("SQL New (from table name)", self.logichub_sql_start_from_table_name)
        self.make_action("SQL New (without table name)", self.logichub_sql_start_without_table_name, alternate=True)
        self.make_action("SQL New with Integration Error Check (from table name)",
                         self.logichub_sql_start_with_integ_error_check)
        self.make_action("SQL New with Integration Error Check (without table name)",
                         self.logichub_sql_start_with_integ_error_check_without_table_name, alternate=True)

        self.make_action("SQL Start from spaced strings", self.logichub_sql_start_from_tabs)
        self.make_action("SQL Start from spaced strings (sorted)", self.logichub_sql_start_from_tabs_sorted)
        self.make_action("SQL Start from spaced strings (distinct)", self.logichub_sql_start_from_tabs_distinct)
        self.make_action("SQL Start from spaced strings (join with left columns)",
                         self.logichub_sql_start_from_tabs_join_left)
        self.make_action("SQL Start from spaced strings (join, left columns only)",
                         self.logichub_tabs_to_columns_left_join, alternate=True)
        self.make_action("SQL Start from spaced strings (join with right columns)",
                         self.logichub_sql_start_from_tabs_join_right)
        self.make_action("SQL Start from spaced strings (join, right columns only)",
                         self.logichub_tabs_to_columns_right_join, alternate=True)

        self.make_action("Clipboard to LH-friendly static string", self.action_logichub_clipboard_to_static_string)

        self.add_menu_section("Spark Commands (from clipboard)", text_color="blue", menu_depth=1)

        # Full version of "from_json" action, which includes all nested dicts and lists
        self.make_action("from_json: full", self.action_spark_from_json)
        self.make_action("from_json: full, allow invalid keys", self.action_spark_from_json_allow_invalid,
                         alternate=True)

        # Lightweight version of "from_json" action, which only captures root keys
        # If a root key's value is a dict, then it will be stored as a string.
        # If it's a list, then it will be stored as a list of strings.
        self.make_action("from_json: no recursion", self.action_spark_from_json_non_recursive)
        self.make_action("from_json: no recursion, allow invalid keys",
                         self.action_spark_from_json_non_recursive_allow_invalid, alternate=True)

        self.make_action("schema_of_json: Create column from JSON clipboard", self.action_json_to_schema_of_json)

        self.add_menu_section("DSL Commands", text_color="blue", menu_depth=1)

        # ToDo Remove "BETA" prefix after this has been used a while
        self.make_action("Reformat DSL command [simple]", self.logichub_dsl_reformat_simple, keyboard_shortcut="CmdOrCtrl+shift+d")
        self.make_action("BETA: Reformat DSL command [pretty print SQL]", self.logichub_dsl_reformat_pretty, keyboard_shortcut="CmdOrCtrl+OptionOrAlt+d")

        self.make_action("Integration Error Check: forceFail and dropColumns", self.logichub_dsl_integ_error_check_forceFail_and_dropColumns)
        self.make_action("Integration Error Check: forceFail and dropColumns (without result)", self.logichub_dsl_integ_error_check_forceFail_and_dropColumns_without_result, alternate=True)

        self.make_action("Add batch info and drop temporary column (from table name)", self.logichub_dsl_batch_info)

        self.add_menu_section("Web UI", text_color="blue", menu_depth=1)

        self.make_action("Event File URL from File Name", self.logichub_event_file_url_from_file_name)
        self.make_action("Event File URL path (static)", self.logichub_event_file_url_static, alternate=True)

        # ------------ Menu Sub-section: LQL operators ------------ #

        self.print_in_menu("LQL: Operators")

        self.add_menu_section("General", text_color="blue", menu_depth=1)

        self.make_action("addExecutionMetadata", self.logichub_operator_start_addExecutionMetadata)
        self.make_action("dropColumns", self.logichub_operator_start_dropColumns)
        self.make_action("ensureTableHasColumns", self.logichub_operator_start_ensureTableHasColumns)
        self.make_action("fieldnamesHistogram", self.logichub_operator_start_fieldnamesHistogram)
        self.make_action("fetchAlerts (with parent table)", self.logichub_operator_start_fetchAlerts_with_table)
        self.make_action("fetchAlerts (without parent table)", self.logichub_operator_start_fetchAlerts_no_table)
        self.make_action("forceFail", self.logichub_operator_start_forceFail)
        self.make_action("getFieldnames", self.logichub_operator_start_getFieldnames)
        self.make_action("jsonToColumns", self.logichub_operator_start_jsonToColumns, menu_depth=1)
        self.make_action("unionAll", self.logichub_operator_start_unionAll, menu_depth=1)
        self.make_action("waitForMillis", self.logichub_operator_start_waitForMillis)

        self.add_menu_section("Joins", text_color="blue", menu_depth=1)

        self.make_action("autoJoin", self.logichub_operator_start_autoJoin, menu_depth=1)
        self.make_action("autoJoinTables", self.logichub_operator_start_autoJoinTables, menu_depth=1)
        self.make_action("joinTables", self.logichub_operator_start_joinTables, menu_depth=1)

        self.add_menu_section("Custom Lists", text_color="blue", menu_depth=1)

        self.make_action("appendToList", self.logichub_operator_start_appendToList)
        self.make_action("appendToListIfNotExist", self.logichub_operator_start_appendToListIfNotExist)
        self.make_action("loadList (with filter)", self.logichub_operator_start_loadList_with_filter)
        self.make_action("loadList (no filter)", self.logichub_operator_start_loadList_without_filter)
        self.make_action("queryFromList", self.logichub_operator_start_queryFromList)
        self.make_action("replaceList", self.logichub_operator_start_replaceList)
        self.make_action("selectivelyDeleteFromList", self.logichub_operator_start_selectivelyDeleteFromList)

        self.print_in_menu("LogicHub Troubleshooting")
        self.make_action("Sanitize playbook JSON for comparison (from clipboard)", self.sanitize_logichub_json)

        self.add_menu_section("runtimeStats (from batch stats json in clipboard)", text_color="blue", menu_depth=1)

        self.make_action("Runtime Stats Sort JSON", self.logichub_runtime_stats_to_json)
        self.make_action("Runtime Stats to CSV", self.logichub_runtime_stats_to_csv)

        self.print_in_menu("Shell: Host")
        self.make_action("Add myself to docker group", self.shell_lh_host_fix_add_self_to_docker_group)
        self.make_action("Own Instance Version", self.logichub_shell_own_instance_version)
        self.make_action("Recent UI user activity", self.logichub_check_recent_user_activity_v2)

        # ToDo Delete this and its method once confirmed it's no longer needed.
        self.make_action("Recent UI user activity (OLD VERSION)", self.logichub_check_recent_user_activity_v1, alternate=True)

        self.make_action("Stop and Start All Services", self.logichub_stop_and_start_services_in_one_line)

        self.make_action("Integration Name from Digest or Container Name", self.logichub_integration_name_from_digest_or_container_name)

        self.add_menu_section("File System Paths", text_color="blue", menu_depth=1)

        self.make_action("lh-monitoring repo", self.shell_lh_host_path_to_lh_monitoring_repo)
        self.make_action("node_data cache", self.shell_lh_host_path_to_node_data)
        self.make_action("service container data", self.shell_lh_host_path_to_service_container_volume)

        self.print_in_menu("Shell: Service Container")
        self.make_action("List Edited Descriptors", self.lh_service_shell_list_edited_descriptors)

        self.print_in_menu("Docker")

        self.make_action("service bash", self.action_docker_service_bash)
        self.make_action("psql shell", self.action_docker_psql_shell)

        self.make_action("psql query without shell", self.action_docker_psql_without_shell)
        self.make_action("psql query without shell (query from clipboard)",
                         self.action_docker_psql_without_shell_from_clipboard, alternate=True)

        self.make_action("psql query without shell, json output", self.action_docker_psql_without_shell_json)
        self.make_action("psql query without shell, json output (query from clipboard)",
                         self.action_docker_psql_without_shell_json_from_clipboard, alternate=True)

        self.print_in_menu("DB: Postgres")

        self.add_menu_section("Flows", text_color="blue", menu_depth=1)

        self.make_action("All Flows, (latest versions only)", self.db_postgres_latest_flows)
        self.make_action("All Flows [old v1], (latest versions only)", self.db_postgres_latest_flows_v1, alternate=True)

        self.make_action("Summarize Flows (latest versions only)", self.db_postgres_summarize_latest_flows)
        self.make_action("Summarize Flows Lite (latest versions only)", self.db_postgres_summarize_latest_flows_lite, alternate=True)

        self.add_menu_section("Modules", text_color="blue", menu_depth=1)

        self.make_action("All Modules, (latest versions only)", self.db_postgres_latest_modules)

        self.add_menu_section("Integrations", text_color="blue", menu_depth=1)

        self.make_action("List Descriptors w/ Docker Images", self.db_postgres_descriptors_and_docker_images)

        self.make_action("List Instances w/ Docker Images", self.db_postgres_instances_and_docker_images)
        self.make_action("List Instances w/ Docker Images (extended)",
                         self.db_postgres_instances_and_docker_images_extended, alternate=True)

        self.make_action("List Instances w/ Docker Images, exclude image in clipboard",
                         self.db_postgres_instances_and_docker_images_exclude_image)
        self.make_action("List Instances w/ Docker Images (extended), exclude image in clipboard",
                         self.db_postgres_instances_and_docker_images_extended_exclude_image, alternate=True)

        self.make_action("List custom integration digests", self.db_postgres_custom_integrations_active_digests)
        self.make_action("List custom integration digests (from bash)", self.db_postgres_custom_integrations_active_digests_from_bash, alternate=True)

        self.add_menu_section("Streams and Batches", text_color="blue", menu_depth=1)

        self.make_action("List executing streams/batches", self.db_postgres_currently_running_streams)

        self.add_menu_section("Users", text_color="blue", menu_depth=1)

        self.make_action("List users with pending password reset", self.db_postgres_users_pending_password_reset)

        self.add_menu_section("Cases", text_color="blue", menu_depth=1)

        self.make_action("Estimate Total Size of a Case (from case ID)", self.db_postgres_cases_total_size)

        # ToDo Update the actions above to give each an alternate version which runs without having to go into psql first

        self.print_in_menu("Integrations")
        self.make_action("integrationsFiles path: LogicHub host", self.clipboard_integration_files_path_logichub_host)
        self.make_action("integrationsFiles path: LogicHub host (from file name)",
                         self.clipboard_integration_files_path_logichub_host_from_file_name, alternate=True)
        self.make_action("integrationsFiles path: integration containers",
                         self.clipboard_integration_files_path_integration_containers)
        self.make_action("integrationsFiles path: integration containers (from file name)",
                         self.clipboard_integration_files_path_integration_containers_from_file_name, alternate=True)
        self.make_action("integrationsFiles path: service container",
                         self.clipboard_integrationsFiles_path_service_container)
        self.make_action("integrationsFiles path: service container (from file name)",
                         self.clipboard_integrationsFiles_path_service_container_from_file_name, alternate=True)

        self.make_action("Copy descriptor file using its image tag", self.copy_descriptor_file_using_image_tag)
        self.make_action("Copy descriptor file using its image tag, then edit original",
                         self.copy_descriptor_file_using_image_tag_then_edit_original, alternate=True)

        self.make_action("Open bash in docker container by product name", self.open_integration_container_by_product_name)
        self.make_action("Prep custom integration container for local editing", self.prep_custom_integration_container)

        self.print_in_menu("LogicHub Upgrades")

        self.add_menu_section("Upgrade Preparation", text_color="blue", menu_depth=1)

        self.make_action("Visual inspection", self.logichub_upgrade_prep_verifications)
        self.make_action("Backups (run as logichub/centos!)", self.logichub_upgrade_prep_backups)
        self.make_action("Backups (skip logs)", self.logichub_upgrade_prep_backups_skip_logs)
        self.make_action("Backups Lite (skip logs and LH backup script)",
                         self.logichub_upgrade_prep_backups_lite, alternate=True)

        self.add_menu_section("Upgrade Commands", text_color="blue", menu_depth=1)

        self.make_action("Upgrade Command (from milestone version in clipboard)",
                         self.logichub_upgrade_command_from_clipboard)
        self.make_action("Upgrade Command (static)", self.logichub_upgrade_command_static, alternate=True)
        self.make_action("Upgrade Command with Backup Script (from milestone version in clipboard)",
                         self.logichub_upgrade_command_from_clipboard_with_backup_script)
        self.make_action("Upgrade Command with Backup Script (static)",
                         self.logichub_upgrade_command_static_with_backup_script, alternate=True)

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
                raise ValueError(f'Keyboard shortcut "{keyboard_shortcut}" already assigned to action "{self.__reserved_keyboard_shortcuts[keyboard_shortcut]}" and cannot be mapped to action {name}')
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
            raise ValueError("The \"lower\" and \"upper\" parameters in Actions.read_clipboard are mutually exclusive. Use one or the other, not both.")
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

    def _lh_read_clipboard_for_table_name(self):
        _input_str = self.read_clipboard()
        if re.search(r'>*?\s', _input_str):
            self.display_notification_error("Invalid input; table name cannot contain spaces")
            exit(1)
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

    def make_upgrade_command(self, version: str = None):
        if not version:
            version = "XX.YY"
        else:
            # To make sure this works whether or not the leading 'm' is provided, strip out any 'm'
            version = version.replace('m', '').strip()
            if not version.strip() or not re.match(r'^\d{2,}\.\d+$', version):
                self.display_notification_error("Invalid LogicHub version ({})".format(version))
        return f"bash <(curl https://s3-us-west-1.amazonaws.com/lhub-installer/installer-m{version}.sh)"

    @staticmethod
    def make_backup_command():
        return "sudo /opt/logichub/scripts/backup.sh"

    def pretty_print_sql(self, input_str, wrap_after=0):
        """
        Reusable method to "pretty print" SQL

        :param input_str:
        :param wrap_after:
        :return:
        """
        try:
            # Replace line breaks with spaces, then trim leading and trailing whitespace
            _output = re.sub(r'[\n\r]+', ' ', input_str).strip()

            # If wrapped in ticks, strip those off. We no longer require them in LogicHub.
            _output = re.sub(r'^`|(?<!\\)`$', '', _output)

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
                if re.findall(fr"\b{cap_field.upper()}\b", _output) and not re.findall(fr"\b{cap_field.upper()}\b", input_str):
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

    ############################################################################
    # LogicHub -> LQL & Web UI

    def logichub_pretty_print_sql(self, **kwargs):
        """
        Pretty Print SQL

        :return:
        """
        _input_str = self.read_clipboard()
        _output = self.pretty_print_sql(_input_str, **kwargs)
        self.write_clipboard(_output)

    def logichub_pretty_print_sql_wrapped(self):
        """
        Pretty Print SQL: Wrapped at 80 characters

        :return:
        """
        self.logichub_pretty_print_sql(wrap_after=80)

    def logichub_pretty_print_sql_compact(self):
        """
        Pretty Print SQL: Compact

        :return:
        """
        self.logichub_pretty_print_sql(wrap_after=99999)

    def _split_tabs_to_columns(self, force_lower=False, sort=False, quote=False, update_clipboard=True):
        _input_str = self.read_clipboard()

        # Strip out commas and quotes in case the user clicked the wrong one and wants to go right back to processing it
        # Strip out pipes too so this can be used on postgresql headers as well
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

    def logichub_tabs_to_columns(self):
        self._split_tabs_to_columns()

    def logichub_tabs_to_columns_lowercase(self):
        self._split_tabs_to_columns(force_lower=True)

    def logichub_tabs_to_columns_sorted(self):
        self._split_tabs_to_columns(sort=True)

    def logichub_tabs_to_columns_sorted_lowercase(self):
        self._split_tabs_to_columns(force_lower=True, sort=True)

    def logichub_tabs_to_columns_and_quotes(self):
        self._split_tabs_to_columns(quote=True)

    def logichub_tabs_to_columns_and_quotes_lowercase(self):
        self._split_tabs_to_columns(quote=True, force_lower=True)

    def logichub_tabs_to_columns_and_quotes_sorted(self):
        self._split_tabs_to_columns(quote=True, sort=True)

    def logichub_tabs_to_columns_and_quotes_sorted_lowercase(self):
        self._split_tabs_to_columns(quote=True, sort=True, force_lower=True)

    def logichub_sql_start_from_table_name(self):
        _input_str = self.read_clipboard()
        self.write_clipboard(f'SELECT * FROM {_input_str}')

    def logichub_sql_start_without_table_name(self):
        self.write_clipboard(f'SELECT * FROM ')

    @staticmethod
    def _logichub_integ_error_sql(table_name=None):
        sql_string = """SELECT REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(CASE\n  WHEN exit_code = 0 AND GET_JSON_OBJECT(result, '$.has_error') = FALSE THEN ''\n  WHEN exit_code = 241 THEN 'timed out before completing'\n  WHEN COALESCEEMPTY(GET_JSON_OBJECT(result, '$.error'), stderr) != '' THEN COALESCEEMPTY(GET_JSON_OBJECT(result, '$.error'), stderr)\n  WHEN exit_code != 0 THEN PRINTF('Unexpected exit code: %s', exit_code)\n  ELSE 'no error provided, but unexpected result: ' || result\nEND,\n  '[\\\\s\\\\S]*Traceback[\\\\s\\\\S]+\\n(?: *File .+\\n.+\\n)+', ''),\n  '\\n.*killed because of Timeout.*', ''),\n  '^(?=.)', 'Integration failed: ') AS integ_error,\n*\nFROM ___table_name___\nORDER BY integ_error DESC"""
        if table_name:
            sql_string = sql_string.replace('___table_name___', table_name)
        return sql_string

    def logichub_sql_start_with_integ_error_check(self):
        _input_str = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(self._logichub_integ_error_sql(_input_str))

    def logichub_sql_start_with_integ_error_check_without_table_name(self):
        self.write_clipboard(self._logichub_integ_error_sql())

    def _reusable_fetch_and_split_dsl_from_clipboard(self):
        new_dsl_list = []
        error_title = "DSL Format Error"

        _input_str = self.read_clipboard()
        if not re.match(r'((?:(?<=^)|(?<=\|))\s*\[.*?]\s+as\s+\w+)+\s*$', _input_str, re.DOTALL):
            self.display_notification_error('Input not recognized as valid DSL', title=error_title)

        for part in [x.strip() for x in re.split(r'\s*\|\s*(?=\[)', _input_str)]:
            part_type = None
            matches = re.search(r'^\[\s*(?P<lql>\S.*?)\s*]\s*as\s*(?P<alias>\w+)', part, re.DOTALL)
            if not matches:
                self.display_notification_error('Unexpected DSL format: empty LQL block found', title=error_title)
            sql_part = matches.group("lql").strip()
            alias_part = matches.group("alias").strip()

            if re.match(r'^(?i)select\s+(?!\()', sql_part) and re.search(r'(?i)\bfrom\b', sql_part):
                part_type = 'sql'
            elif re.match(r'^\w+\s*\(.+\)$', sql_part.strip(), re.DOTALL):
                part_type = 'operator'
            else:
                self.display_notification_error(f'Unexpected DSL format: unable to parse: {sql_part}')

            new_dsl_list.append({
                'lql': sql_part,
                'alias': alias_part,
                'type': part_type
            })

        if not new_dsl_list:
            self.display_notification_error('An error occurred: split DSL list came out empty', title=error_title)
        return new_dsl_list

    def logichub_dsl_reformat_simple(self):
        """ Reformat DSL command [simple] """
        dsl_parts = self._reusable_fetch_and_split_dsl_from_clipboard()
        new_dsl_string = ""
        for part in dsl_parts:
            new_dsl_string += f'[\n    {part["lql"]}\n] as {part["alias"]}\n\n| '
        if not new_dsl_string:
            self.display_notification_error('An error occurred: new DSL string came out empty', title="Reformat DSL command")
        self.write_clipboard(new_dsl_string[0:-4])

    def logichub_dsl_reformat_pretty(self):
        """ Reformat DSL command [pretty print SQL] """
        dsl_parts = self._reusable_fetch_and_split_dsl_from_clipboard()
        print(json.dumps(dsl_parts, indent=2))
        new_dsl_string = ""
        for part in dsl_parts:
            sql_part = sql = part["lql"]
            alias_part = part["alias"]
            if part['type'] == 'sql':
                sql = self.pretty_print_sql(sql_part).replace('\n', '\n    ')
            new_dsl_string += f'[\n    {sql}\n] as {alias_part}\n\n| '
        if not new_dsl_string:
            self.display_notification_error('An error occurred: new DSL string came out empty', title="Reformat DSL command")
        self.write_clipboard(new_dsl_string[0:-4])

    def logichub_dsl_integ_error_check_forceFail_and_dropColumns(self):
        """ Integration Error Check: forceFail and dropColumns only """
        _input_str = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(
            f'[forceFail({_input_str}, "integ_error")] as t__fail_if_error\n| [dropColumns(t__fail_if_error, "integ_error", "exit_code", "stdout", "stderr")] as t__final_output')

    def logichub_dsl_integ_error_check_forceFail_and_dropColumns_without_result(self):
        """ Integration Error Check: forceFail and dropColumns only (without result column) """
        _input_str = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(
            f'[forceFail({_input_str}, "integ_error")] as t__fail_if_error\n| [dropColumns(t__fail_if_error, "result", "integ_error", "exit_code", "stdout", "stderr")] as t__final_output')

    def logichub_dsl_batch_info(self):
        template = r"""[
  addExecutionMetadata({table})
] as t1

| [
  SELECT *,
    BIGINT(GET_JSON_OBJECT(lhub_execution_metadata, "$.interval_start_millis")) AS interval_start_millis,
    BIGINT(GET_JSON_OBJECT(lhub_execution_metadata, "$.interval_end_millis")) AS interval_end_millis,
    GET_JSON_OBJECT(lhub_execution_metadata, "$.batch_url") AS batch_url
  FROM t1
] as t2

| [
  dropColumns(t2, "lhub_execution_metadata")
] as t_output"""
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(template.format(table=table_name))

    def logichub_sql_start_from_tabs(self):
        _columns_formatted = self._split_tabs_to_columns(update_clipboard=False)
        self.write_clipboard(f'SELECT {_columns_formatted}\nFROM ')

    def logichub_sql_start_from_tabs_sorted(self):
        _columns_formatted = self._split_tabs_to_columns(update_clipboard=False, sort=True)
        self.write_clipboard(f'SELECT {_columns_formatted}\nFROM ')

    def logichub_sql_start_from_tabs_distinct(self):
        _columns_formatted = self._split_tabs_to_columns(update_clipboard=False)
        self.write_clipboard(f'SELECT DISTINCT {_columns_formatted}\nFROM ')

    def logichub_tabs_to_columns_left_join(self):
        _input_str = self._split_tabs_to_columns(update_clipboard=False)
        _columns = re.split(', *', _input_str)
        self.write_clipboard("L.{}".format(", L.".join(_columns)))

    def logichub_tabs_to_columns_right_join(self):
        _input_str = self._split_tabs_to_columns(update_clipboard=False)
        _columns = re.split(', *', _input_str)
        self.write_clipboard("R.{}".format(", R.".join(_columns)))

    def action_logichub_clipboard_to_static_string(self):
        _input_str = self.read_clipboard(trim_input=False)
        # Sanitize escapes
        _input_str = re.sub(r'\\', r'\\\\', _input_str)
        # Sanitize single quotes
        # _input_str = re.sub("'", r"\\'", _input_str)
        _input_str = _input_str.replace("'", "\\'")
        # Sanitize newlines
        _input_str = _input_str.replace('\n', '\\n')
        # Escape tick marks
        _input_str = _input_str.replace('`', '\\`')
        self.write_clipboard(f"'{_input_str}'")

    def logichub_sql_start_from_tabs_join_left(self):
        _input_str = self._split_tabs_to_columns(update_clipboard=False)
        _columns = re.split(', *', _input_str)
        _columns_formatted = "L.{}".format(", L.".join(_columns))
        self.write_clipboard(f'SELECT {_columns_formatted}\nFROM xxxx L\nLEFT JOIN xxxx R\nON L.xxxx = R.xxxx')

    def logichub_sql_start_from_tabs_join_right(self):
        _input_str = self._split_tabs_to_columns(update_clipboard=False)
        _columns = re.split(', *', _input_str)
        _columns_formatted = "R.{}".format(", R.".join(_columns))
        self.write_clipboard(f'SELECT {_columns_formatted}\nFROM xxxx L\nLEFT JOIN xxxx R\nON L.xxxx = R.xxxx')

    def logichub_event_file_url_from_file_name(self):
        _input_str = self.read_clipboard()
        self.write_clipboard(f'file:///opt/docker/data/service/event_files/{_input_str}')

    def logichub_event_file_url_static(self):
        self.write_clipboard(f'file:///opt/docker/data/service/event_files/')

    @staticmethod
    def _strip_json_for_spark(input_value, replace_nones=True):
        def run_strip(obj):
            # Spark's "schema_of_json" defines the data type as null if a string is completely empty,
            # so return "x" for strings so that there is always exactly 1 character in all strings
            if obj is None or isinstance(obj, str):
                # If nulls are present, or if it's already just a string, then return a single character string
                return "x"
            elif type(obj) is bool:
                return obj
            elif isinstance(obj, Number):
                if type(obj) is int:
                    return 1
                else:
                    return float(1.1)

            elif isinstance(obj, list):
                # First drop null values from the list
                obj = [x for x in obj if x is not None]
                if not obj:
                    # If a list is empty, assume that it's a list of strings
                    return ["x"]

                # Spark is less forgiving than json.loads, so determine the best type to use if there is a mix of types
                single_value = obj[0]
                for value in obj:
                    if type(single_value) is str or type(value) is str:
                        # If any value in the list is a string, then just return a list of a single string entry so all will be read as strings
                        return ["x"]
                    elif type(single_value) is not type(value):
                        # If there is any difference in type between entries, determine which type to use
                        if isinstance(single_value, Number) and isinstance(value, Number):
                            # If both are numeric then just stick with a float
                            if type(single_value) is not float:
                                single_value = float(1.1)
                        else:
                            # If there is any other kind of mismatch other than numeric types, then force it to be a string.
                            # JSON & Python will allow a list to contain a mix of types (such as lists, dicts, numbers, etc.),
                            # but Spark insists on arrays having a common type.
                            return ["x"]

                # If it's made it this far, then the types are at least consistent. Now we just need to shorten/flatten.
                if type(single_value) is int:
                    # For int, shorten to just 1
                    return 1
                elif type(single_value) is float:
                    # for float, shorten to just 1.1
                    return float(1.1)
                elif not isinstance(single_value, (list, dict)):
                    # In case I've overlooked any other types, then as long as the values are lists or dicts then just return as-is
                    return single_value
                elif isinstance(single_value, list):
                    # This is just a best-effort feature, so if it's a list of lists by this point, then just return with one list entry containing just one string
                    return [["x"]]
                elif isinstance(single_value, dict):
                    if len(obj) == 1:
                        # If there's only one dict present, then run the one entry back through on its own and then return a list with that single entry
                        return [run_strip(obj[0])]
                    else:
                        # If it's made it this far, then it's a list containing multiple dicts, so merge all of the dicts recursively, and then run the single dict back through the function
                        return [run_strip(Reusable.dict_merge(*obj))]
                else:
                    raise TypeError("Unknown Error: Should never actually reach this point")

            elif isinstance(obj, dict):
                # Workaround: If a dict is empty, then schema_of_json will say it's a struct without keys (or just fail), so make it a string instead
                if not obj:
                    return "{}"
                return {k: run_strip(v) for k, v in obj.items()}

            else:
                # Just in case there are any types not covered by this point, return as-is
                return obj

        def replace_none_values(obj):
            pass
            return obj

        input_value = run_strip(input_value)
        if replace_nones:
            input_value = replace_none_values(input_value)

        return input_value

    def action_spark_from_json(self, recursive=True, block_invalid_keys=True):
        def check_for_invalid_characters(input_var):
            if not isinstance(input_var, (dict, list)):
                return
            invalid_keys = []
            if isinstance(input_var, dict):
                for k, v in input_var.items():
                    if re.findall(r'\W', k):
                        invalid_keys.append(k)
                    _invalid = check_for_invalid_characters(v)
                    if _invalid:
                        invalid_keys.extend(_invalid[1])
            elif isinstance(input_var, list):
                for v in input_var:
                    _invalid = check_for_invalid_characters(v)
                    if _invalid:
                        invalid_keys.extend(_invalid[1])
            if invalid_keys:
                return True, list(set(invalid_keys))

        def flatten(obj):
            if not isinstance(obj, (dict, list)):
                return obj
            elif isinstance(obj, list):
                return [flatten(x) for x in obj]
            else:
                for k in list(obj.keys()):
                    if isinstance(obj[k], dict):
                        obj[k] = "{}"
                    elif isinstance(obj[k], list):
                        obj[k] = ["x"]
                return obj

        def format_for_spark(_input_str):
            types = {
                str: "STRING",
                bool: "BOOLEAN",
                float: "DOUBLE",
                int: "BIGINT",
            }
            if type(_input_str) in types.keys():
                return types[type(_input_str)]

            if isinstance(_input_str, dict):
                format_str = "STRUCT<"
                for k, v in _input_str.items():
                    format_str += f"{k}: {format_for_spark(v)}, "

                if format_str.endswith(", "):
                    format_str = format_str[:-2]
                format_str += '>'
                return format_str
            elif isinstance(_input_str, list):
                format_str = f"ARRAY<{format_for_spark(_input_str[0])}>"
            else:
                raise TypeError(f"Unmapped data type: {type(_input_str)}")
            return format_str

        # Read clipboard, but drop single quotes if any are found
        _input_str = self.read_clipboard().replace("'", "")
        # Convert json to dict or list
        json_loaded = self._json_notify_and_exit_when_invalid(manual_input=_input_str)
        json_updated = self._strip_json_for_spark(json_loaded)
        if not recursive:
            json_updated = flatten(json_updated)
        if block_invalid_keys:
            invalid = check_for_invalid_characters(json_updated)
            if invalid:
                error = f"INVALID KEY IN JSON: {', '.join(invalid[1])}"
                self.write_clipboard(f"\n***** {error} *****\n\n", skip_notification=True)
                self.display_notification_error(error)
                return

        try:
            _output = f"FROM_JSON(result, '{format_for_spark(json_updated)}') AS result_struct"
        except TypeError as e:
            _output = str(e)
            self.fail_action_with_exception(exception=e)
        self.write_clipboard(_output)

    def action_spark_from_json_allow_invalid(self):
        self.action_spark_from_json(block_invalid_keys=False)

    def action_spark_from_json_non_recursive(self):
        self.action_spark_from_json(recursive=False)

    def action_spark_from_json_non_recursive_allow_invalid(self):
        self.action_spark_from_json(recursive=False, block_invalid_keys=False)

    def action_json_to_schema_of_json(self):
        # Read clipboard, but drop single quotes if any are found
        _input_str = self.read_clipboard().replace("'", "")
        # Convert json to dict or list
        json_loaded = self._json_notify_and_exit_when_invalid(manual_input=_input_str)
        json_updated = self._strip_json_for_spark(json_loaded)
        json_text = json.dumps(json_updated, ensure_ascii=False, separators=(', ', ': '))
        _output = f"SCHEMA_OF_JSON('{json_text}') AS json_test"
        self.write_clipboard(_output)

    def sanitize_logichub_json(self):
        def crawl(data):
            if isinstance(data, dict):
                number_fields_to_sanitize = ["integrationInstanceId", "id"]
                fields_to_delete = [
                    "x", "y", "__lh_is_default_connection", "__lh_use_agent", "userPreference",
                ]
                # string_fields_to_sanitize = ["id", "nodeId", "flowId", "oldId"]
                # If a value is a string, treat as a regex pattern.
                string_fields_to_sanitize = {
                    "id": None, "nodeId": None, "flowId": None, "oldId": None,
                    "__lh_is_default_connection": None, "currentModified": None,
                    "baselineNode": None,
                    "table": "list_data_",
                    "flow": "flow-",
                    "baseline": "stream-",
                    "flowNodeReferenceId": "flowNodeRef-",
                }
                list_fields_to_sanitize = ["executionDependsOn"]
                list_fields_to_empty = ["warnings"]
                lql_fields = ["templateLQL", "lql"]
                for k in list(data.keys()):
                    if k in lql_fields and isinstance(data[k], str):
                        data[k] = re.sub(r'^`|((?<!\\)`|\n)+$', '', data[k])
                    if k in fields_to_delete:
                        del data[k]
                    elif isinstance(data[k], Number) and k in number_fields_to_sanitize:
                        data[k] = 0
                    elif isinstance(data[k], str):
                        if k.endswith('**connection') or k in string_fields_to_sanitize and (not string_fields_to_sanitize[k] or re.match(string_fields_to_sanitize[k], data[k])):
                            data[k] = "..."
                    elif isinstance(data[k], list):
                        if k in list_fields_to_sanitize:
                            data[k] = ["" for _ in data[k]]
                        elif k in list_fields_to_empty:
                            data[k] = []
                        # If the key is "inputs" and the value is a list of strings, then replace each string with "..." so it doesn't end up a list of unique node IDs
                        if k == "inputs" and data[k] and isinstance(data[k][0], str):
                            data[k] = ["..." for _ in data[k]]
                # crawl through values of every k in the dict
                data = {k: crawl(v) for k, v in data.items()}

            elif isinstance(data, list):
                data = [crawl(d) for d in data]

                # for lists of dicts, if there is a name field, sort by the name
                if data and isinstance(data[0], dict):
                    has_name = True
                    for node in data:
                        if not isinstance(node, dict):
                            has_name = False
                            break
                        if not node.get("name"):
                            has_name = False
                            break
                        if node.get("name") == "Output" and node.get("kind") == "output" and node.get("nodes"):
                            node["nodes"] = ["" for _ in node["nodes"]]

                    if has_name:
                        data = sorted(data, key=lambda i: i['name'])

            return data

        def _final_sort(data):
            if isinstance(data, dict):
                new_dict = {}
                for k in ['name']:
                    if k in data.keys():
                        new_dict[k] = data.pop(k)
                new_dict.update(data)
                return {k: _final_sort(v) for k, v in new_dict.items()}
            elif isinstance(data, list):
                return [_final_sort(s) for s in data]
            else:
                return data

        _input_str = self._json_notify_and_exit_when_invalid()
        if not _input_str:
            return
        _input_str = self._process_json_clipboard(sort_output=True, format_output=True, return_obj=True)

        # First round of sanitizing
        _input_str = crawl(_input_str)

        # Sort results by keys and values
        _input_str = self._sort_dicts_and_lists(_input_str)

        # Custom final overall sorting
        _input_str = _final_sort(_input_str)

        # One more sort, this time ONLY for the list of nodes to be ordered by node name
        for n in range(len(_input_str['flows'])):
            _input_str['flows'][n]['nodes'] = sorted(_input_str['flows'][n]['nodes'], key=lambda i: i['name'])

        self.write_clipboard(json.dumps(_input_str, ensure_ascii=False, indent=2))

    # ---- Operators: General ----

    def logichub_operator_start_addExecutionMetadata(self):
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'addExecutionMetadata({table_name})')

    def logichub_operator_start_dropColumns(self):
        """Operator Start: dropColumns"""
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'dropColumns({table_name}, "COLUMN_NAME")')

    def logichub_operator_start_ensureTableHasColumns(self):
        """Operator Start: ensureTableHasColumns"""
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'ensureTableHasColumns({table_name}, "COLUMN_NAME")')

    def logichub_operator_start_fieldnamesHistogram(self):
        """Operator Start: fieldnamesHistogram"""
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'fieldnamesHistogram({table_name})')

    def logichub_operator_start_fetchAlerts_with_table(self, include_table_name=True):
        table_reference = ''
        if include_table_name:
            table_reference = f', {self._lh_read_clipboard_for_table_name()}'
        self.write_clipboard(f'fetchAlerts("QUERY", 100000{table_reference})')

    def logichub_operator_start_fetchAlerts_no_table(self):
        self.logichub_operator_start_fetchAlerts_with_table(include_table_name=False)

    def logichub_operator_start_forceFail(self):
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'forceFail({table_name}, "integ_error")')

    def logichub_operator_start_getFieldnames(self):
        """Operator Start: getFieldnames"""
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'getFieldnames({table_name})')

    def logichub_operator_start_jsonToColumns(self):
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'jsonToColumns({table_name}, "result")')

    def logichub_operator_start_unionAll(self):
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'unionAll({table_name}, TABLE2)')

    def logichub_operator_start_waitForMillis(self):
        """Operator Start: waitForMillis"""
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'waitForMillis({table_name}, NUMBER)')

    # ---- Operators: Joins ----

    def logichub_operator_start_autoJoin(self):
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'autoJoin({table_name}, TABLE2)')

    def logichub_operator_start_autoJoinTables(self):
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'autoJoinTables([{table_name}, TABLE2])')

    def logichub_operator_start_joinTables(self):
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'joinTables([{table_name}, TABLE2], [], "JOIN_TYPE")')

    # ---- Operators: Custom Lists ----

    def reusable_get_custom_list_name_from_clipboard(self):
        _input_str = self.read_clipboard()
        return re.sub('^"|"$', '', _input_str)

    def logichub_operator_start_appendToList(self):
        """Operator Start: appendToList"""
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'appendToList({table_name}, "LIST_NAME")')

    def logichub_operator_start_appendToListIfNotExist(self):
        """Operator Start: appendToListIfNotExist"""
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'appendToListIfNotExist({table_name}, "LIST_NAME", ["COLUMN1", "COLUMN2"])')

    def logichub_operator_start_loadList_without_filter(self, return_data=False):
        """Operator Start: loadList"""
        list_name = self.reusable_get_custom_list_name_from_clipboard()
        output = f'loadList("{list_name}"'
        if return_data:
            return output
        self.write_clipboard(output + ')')

    def logichub_operator_start_loadList_with_filter(self):
        """Operator Start: loadList"""
        output = self.logichub_operator_start_loadList_without_filter(return_data=True)
        self.write_clipboard(output + ', "FILTER")')

    def logichub_operator_start_queryFromList(self):
        """Operator Start: queryFromList"""
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'queryFromList("LIST_NAME", "FILTER", {table_name})')

    def logichub_operator_start_replaceList(self):
        """Operator Start: replaceList"""
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'replaceList({table_name}, "LIST_NAME")')

    def logichub_operator_start_selectivelyDeleteFromList(self):
        """Operator Start: selectivelyDeleteFromList"""
        table_name = self._lh_read_clipboard_for_table_name()
        self.write_clipboard(f'selectivelyDeleteFromList("LIST_NAME", "FILTER", {table_name})')

    def _logichub_runtime_stats_sort_by_longest(self):
        _input_str = self._json_notify_and_exit_when_invalid()
        if not _input_str:
            return
        _stats = _input_str.get("runtimeStats")
        if "runtimeStats" not in _input_str.keys():
            self.display_notification_error("runtimeStats key not found")
            return
        elif not _input_str.get("runtimeStats"):
            self.display_notification_error("runtimeStats key not found")
            return
        _stats = dict(Reusable.sort_dict_by_values(_stats, reverse=True))
        _input_str["runtimeStats"] = _stats
        return _input_str

    def logichub_runtime_stats_to_json(self):
        _stats = self._logichub_runtime_stats_sort_by_longest()
        if not _stats:
            return
        _stats_only = _stats.get("runtimeStats")
        self.write_clipboard(json.dumps(_stats, indent=2))
        self.display_notification(f"Total processing time: {sum(_stats_only.values())}")

    def logichub_runtime_stats_to_csv(self):
        _stats = self._logichub_runtime_stats_sort_by_longest()
        if not _stats:
            return

        _stats_only = _stats.get("runtimeStats")
        total_time = sum(_stats_only.values())
        csv_file = Reusable.generate_temp_file_path("csv", prefix="runtime_stats_")
        _stats_for_csv = {
            "executionTimeMs": _stats.get("executionTimeMs"),
            "VIRTUAL TOTAL": total_time,
        }
        _stats_for_csv.update(_stats_only)
        dict_data = [{"node_name": x, "time": y} for x, y in _stats_for_csv.items()]

        with open(csv_file, 'w') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=['node_name', 'time'])
            writer.writeheader()
            for data in dict_data:
                writer.writerow(data)

        _ = subprocess.run(["open", csv_file], capture_output=True, universal_newlines=True)
        self.display_notification(f"Total processing time: {total_time}")

    ############################################################################
    # LogicHub -> Shell: Host
    def shell_lh_host_fix_add_self_to_docker_group(self):
        self.write_clipboard(f'sudo usermod -a -G docker {self.config.local_user}')

    def shell_lh_host_path_to_service_container_volume(self):
        self.write_clipboard('/var/lib/docker/volumes/logichub_data/_data/service/')

    def shell_lh_host_path_to_lh_monitoring_repo(self):
        self.write_clipboard('/var/lib/docker/volumes/logichub_data/_data/shared/lh-monitoring/mdr_prod_local_scripts/')

    def shell_lh_host_path_to_node_data(self):
        self.write_clipboard('/var/lib/docker/volumes/logichub_data/_data/shared/node_data/')

    def logichub_check_recent_user_activity_v1(self):
        self.write_clipboard(r"""check_recent_user_activity() {
    # New consolidated list of all users who have logged in during the current and previous log files
    previous_service_log="$(find /var/log/logichub/service -name "service.log.2*gz"| sort | tail -n1)"
    users_all=($(sudo zgrep -ohP "Login request: *\K\S+" "${previous_service_log}" /var/log/logichub/service/service.log | grep -Pv 'lh-monitoring' | sort -u))
    printf "Users who have logged in recently:\n\n"
    printf "    %s\n" "${users_all[@]}" | sort -u | grep -P ".*"

    printf "\n\nLatest activity:\n\n"
    for i in "${users_all[@]}"; do printf "    %s\n" "$(zgrep -ih "user: ${i}" "${previous_service_log}" /var/log/logichub/service/service.log | grep -P "^\d{4}-" | tail -n1 | grep "${i}")"; done | sort -u | grep -P "^ *20\d{2}-\d{2}-\d{2} [\d:.]+ [+\d]+|(?<=User: )[^\s\(]+"
    printf "\n\nCurrent date:\n\n"
    printf "    %s\n" "$(TZ=UTC date +"%Y-%m-%d %H:%M:%S (%Z)")"
    printf "\n"
}
check_recent_user_activity
""")

    def logichub_check_recent_user_activity_v2(self):
        self.write_clipboard(r""" printf "%s\n\nCurrent date:\n\n    %s\n\n" "$(docker exec postgres psql -P pager --u daemon system_events -c "select regexp_replace(to_char(lhub_ts, 'YYYY-MM-DD HH24:MI:SS OF'), '[+]+00$', '(UTC)') AS lhub_ts_str, username, event_type from (select * from (select *, max(id) over (partition by username) as max_id from system_events WHERE (user_agent != '' OR event_type = 'UserLoginSuccess') AND username NOT IN ('system', 'mdr-automation', 'lh-monitoring', 'StreamsManagerBatchExecutor') AND event_type NOT IN ('BatchExecuted')) s1 where id = max_id AND lhub_ts > NOW() - INTERVAL '24 HOURS') s2 where event_type NOT IN ('UserLoginFailed', 'UserLogoutSuccess', 'UserAccountLocked') AND LOWER(event_type) NOT LIKE 'batch%' order by lhub_ts asc")" "$(TZ=UTC date +"%Y-%m-%d %H:%M:%S (%Z)")" """.strip())

    def logichub_stop_and_start_services_in_one_line(self):
        self.write_clipboard(
            "sudo /opt/logichub/scripts/stop_logichub_sw.sh ; sleep 5 ; sudo /opt/logichub/scripts/start_logichub_sw.sh")

    def logichub_integration_name_from_digest_or_container_name(self):
        """ Integration Name from Digest or Container Name """
        _input_str = self.read_clipboard(lower=True, strip_carriage_returns=True)
        digest_ids = []
        for line in re.split(r'\n+', _input_str):
            if 'lhub-managed-custom-python-' in line:
                digest_ids.append(re.sub(r'^.*lhub-managed-custom-python-(\w+)[\s\S]*', r'\1', line))
            elif '-' not in line:
                digest_ids.append(line.strip())
        digest_id_str = "', '".join(digest_ids)
        self.write_clipboard(
            f'docker exec postgres psql --u daemon lh -t -c "select integration_name, active_digest from custom_integration_meta where lower(active_digest) in (\'{digest_id_str}\')"')

    def logichub_shell_own_instance_version(self):
        self.write_clipboard(
            rf"""curl -s --insecure https://localhost/api/version | grep -Po '"version" : "\K[^"\s]+'""")

    def copy_descriptor_file_using_image_tag(self):
        """
        Copy descriptor file using its image tag in the file name

        :return:
        """
        _input_str = self.read_clipboard()
        self.write_clipboard(
            f"""cp -p "{_input_str}" "{_input_str}.$(grep -Po '"image"[ \\t]*:[ \\t]*"\\K[^"]+' "{_input_str}" | sed -E 's/^.*://')-$(date +'%Y%m%d_%H%M%S')" """)

    def copy_descriptor_file_using_image_tag_then_edit_original(self):
        """
        Copy descriptor file using its image tag, then edit original

        :return:
        """
        _input_str = self.read_clipboard()
        self.write_clipboard(
            f"""cp -p "{_input_str}" "{_input_str}.$(grep -Po '"image"[ \\t]*:[ \\t]*"\\K[^"]+' "{_input_str}" | sed -E 's/^.*://')-$(date +'%Y%m%d_%H%M%S')"; vi "{_input_str}" """)

    def open_integration_container_by_product_name(self):
        """
        Open bash in docker container by product name

        :return:
        """
        self.write_clipboard(
            r"""lh_open_docker_image_by_product_name() { search_str=$1; [[ -z $search_str ]] && echo && read -p "Type part of the product name: " -r search_str; [[ -z $search_str ]] && echo "No search string provided; aborted" && return; mapfile -t newest < <(docker ps|grep -iP "lhub-managed-integrations.logichub.[^.\s]*$search_str"|head -n1|sed -E 's/ +/\n/g'); [[ -z ${newest[0]} ]] && echo "No matching docker image found" && return; echo; echo "${newest[-1]}"|grep -Po 'logichub\.\K[^.]+'; printf 'Image ID: %s\nImage Name: %s\n\n' ${newest[0]} ${newest[1]}; docker exec -it "${newest[0]}" /bin/bash; }; lh_open_docker_image_by_product_name """)

    def prep_custom_integration_container(self):
        """
        Prep custom integration container for local editing

        :return:
        """
        _command = rf"""apt-get update && apt-get install vim -y && if [[ -f ~/.vimrc ]]; then sed -E -i".$(date +'%Y%m%d_%H%M%S').bak" '/^ *set *((no)?number|mouse)/d' ~/.vimrc; fi; printf "set mouse-=a\nset number\n" >> ~/.vimrc && cd /code && mkdir /code/_orig && cp -p /code/*.* /code/_orig && ls -l"""
        self.write_clipboard(_command)

    ############################################################################
    # LogicHub -> Shell: Service Container

    def lh_service_shell_list_edited_descriptors(self):
        self.write_clipboard(
            r"""ls -l /opt/docker/resources/integrations |grep -P "\.json" | grep -v "$(ls -l /opt/docker/resources/integrations |grep -P '\.json$' | awk '{print $6" "$7" "$8}'|sort|uniq -c|sed -E 's/^ *//'|sort -nr|head -n1|grep -Po ' \K.*')" """)

    ############################################################################
    # LogicHub -> Docker

    def action_docker_service_bash(self):
        self.write_clipboard('docker exec -it service /bin/bash\n')

    def action_docker_psql_shell(self):
        self.write_clipboard('docker exec -it postgres psql --u daemon lh\n\\pset pager off\n')

    def action_docker_psql_without_shell(self, text=None):
        text = (text if text else "...").replace('"', r'\"')
        self.write_clipboard(f'docker exec -it postgres psql -P pager --u daemon lh -c "{text}"')

    def action_docker_psql_without_shell_from_clipboard(self):
        self.action_docker_psql_without_shell(text=self.read_clipboard())

    def action_docker_psql_without_shell_json(self, text=None):
        text = (text if text else "...").replace('"', r'\"')
        self.write_clipboard(
            f'docker exec postgres psql -P format=unaligned --u daemon lh -t -c "select json_agg(a) as results from ({text}) a"')

    def action_docker_psql_without_shell_json_from_clipboard(self):
        self.action_docker_psql_without_shell_json(text=self.read_clipboard())

    ############################################################################
    # LogicHub -> DB: Postgres

    def db_postgres_descriptors_and_docker_images(self):
        self.write_clipboard(
            """select id, modified, substring(descriptor from '"image" *: *"([^"]*?)') as docker_image from integration_descriptors order by id;""")

    def _build_query_instances_and_docker_images(self, extended=False, exclude=False):
        extended_fields = "" if not extended \
            else """integration_id, substring(cast(descriptor::json->'runtimeEnvironment'->'descriptor'->'image' as varchar) from ':([^:]+?)"$') as "Docker tag", """
        query_string = f"""select substring(cast(descriptor::json->'name' as varchar) from '"(.+)"') as "Integration Name", label, id, substring(cast(descriptor::json->'version' as varchar) from '"(.+)"') as "Integration Version", {extended_fields}substring(cast(descriptor::json->'runtimeEnvironment'->'descriptor'->'image' as varchar) from '"(.+)"') as "Full Docker Image" from integration_instances order by integration_id, label"""

        if exclude:
            _input_str = self.read_clipboard(trim_input=True)
            return f"""select * from ({query_string}) a where "Full Docker Image" not like '{_input_str}';"""
        else:
            return f"{query_string};"

    def db_postgres_instances_and_docker_images(self):
        self.write_clipboard(self._build_query_instances_and_docker_images(extended=False, exclude=False))

    def db_postgres_instances_and_docker_images_extended(self):
        self.write_clipboard(self._build_query_instances_and_docker_images(extended=True, exclude=False))

    def db_postgres_instances_and_docker_images_exclude_image(self):
        self.write_clipboard(self._build_query_instances_and_docker_images(extended=False, exclude=True))

    def db_postgres_instances_and_docker_images_extended_exclude_image(self):
        self.write_clipboard(self._build_query_instances_and_docker_images(extended=True, exclude=True))

    def db_postgres_custom_integrations_active_digests(self, return_value=False):
        """ Lookup the active digest for all custom integration descriptors in order to help find their docker containers

        :return:
        """
        query_string = f"""SELECT SUBSTRING(integration_descriptors.descriptor FROM '"name" *: *"([^"]*?)') AS integ_name,
  custom_integration_meta.active_digest
FROM integration_descriptors
LEFT JOIN custom_integration_meta
ON integration_descriptors.id = custom_integration_meta.integration_id
WHERE integration_descriptors.id LIKE '%custom%'
ORDER BY integ_name;"""
        if return_value:
            return query_string
        else:
            self.write_clipboard(query_string)

    def db_postgres_custom_integrations_active_digests_from_bash(self):
        command = 'docker exec postgres psql -P pager --u daemon lh -c "{query}"'
        command = re.sub(
            r'\n *', ' ',
            command.format(
                query=self.db_postgres_custom_integrations_active_digests(
                    return_value=True
                ).replace(
                    '"', r'\"'
                )
            )
        )
        self.write_clipboard(command)

    def db_postgres_currently_running_streams(self):
        """ List executing streams/batches """
        self.write_clipboard(
            r"""select b.name as "Stream Name", a.id as "Batch ID", substring(a.stream_id from '"(.+)"') as "Stream ID", a.id as "Batch ID", b.flow as "Flow ID" from batches a left join streams b on substring(a.stream_id from '(\d+)') :: int = b.id where state = 'executing' order by "Stream ID", "Batch ID";"""
        )

    def db_postgres_latest_flows(self):
        """ All Flows [old v1], (latest versions only) """
        self.write_clipboard(
            """WITH temp__flows AS (\n    SELECT * FROM (\n    	SELECT *, MAX(version) OVER (PARTITION BY id) AS max_version\n    	FROM versioned_flows\n    ) a\n    WHERE version = max_version\n)\nSELECT * FROM temp__flows;"""
        )

    def db_postgres_latest_flows_v1(self):
        """ All Flows, (latest versions only) """
        self.write_clipboard(
            """SELECT * FROM (SELECT *, MAX(version) OVER (PARTITION BY id) AS max_version FROM versioned_flows) a WHERE version = max_version;"""
        )

    def db_postgres_latest_modules(self):
        self.write_clipboard(
            """WITH temp__modules AS (\n    SELECT * FROM (\n    	SELECT *,\n    	       FORMAT('%s.%s.%s', new_content_resource_version::JSON->'majorVersion', new_content_resource_version::json->'minorVersion', new_content_resource_version::json->'patchVersion') AS version,\n    	       MAX(FORMAT('%s.%s.%s', new_content_resource_version::JSON->'majorVersion', new_content_resource_version::json->'minorVersion', new_content_resource_version::json->'patchVersion')) OVER (PARTITION BY id) AS max_version\n    	FROM steps\n    ) a\n    WHERE version = max_version\n)\nSELECT * FROM temp__modules;"""
        )

    def db_postgres_summarize_latest_flows(self):
        """ Summarize Flows (latest versions only) """
        self.write_clipboard(
            """select b.name as "Current Name", a.id as "Flow ID", b.version as "Current Version", b.created_at as "Last Modified", c.created_at as "Original Create Date" from (select id, min(version) as min_version, max(version) as max_version from versioned_flows group by id) a left join versioned_flows b on a.id = b.id and a.max_version = b.version left join versioned_flows c on a.id = c.id and a.min_version = c.version order by "Current Name";"""
        )

    def db_postgres_summarize_latest_flows_lite(self):
        """ Summarize Flows Lite (latest versions only) """
        self.write_clipboard(
            """select b.name, a.id, a.max_version from (select id, min(version) as min_version, max(version) as max_version from versioned_flows group by id) a left join versioned_flows b on a.id = b.id and a.max_version = b.version;"""
        )

    def db_postgres_users_pending_password_reset(self):
        """ List users with pending password reset """
        self.write_clipboard(
            r"""select username, failed_attempts, ROUND(EXTRACT(epoch FROM current_date - password_modified_at)/3600/24) as days_pending from users where password_needs_reset = true and is_enabled = true and is_deleted = false;"""
        )

    def db_postgres_cases_total_size(self):
        _input_str = self.read_clipboard(lower=True)
        m = re.search(r'^(?=[a-z]+-)?(\d+)$', _input_str)
        if not m:
            self.display_notification_error("Text in clipboard is not a valid case ID")
        _input_str = m[0]
        self.write_clipboard(
            rf"""\set TEMP__CASE_ID {_input_str}
WITH temp__sizes AS (
    SELECT octet_length(t.*::text) AS s FROM case_field_values AS t WHERE case_id = :TEMP__CASE_ID
  UNION
    SELECT octet_length(t.*::text) AS s FROM cases AS t WHERE id = :TEMP__CASE_ID
  UNION
    SELECT octet_length(t.*::text) AS s FROM comments t WHERE cm_entity_id = :TEMP__CASE_ID
  UNION
    SELECT octet_length(t.*::text) AS s FROM history t WHERE cm_entity_id = :TEMP__CASE_ID
  UNION
    SELECT size_bytes AS s FROM case_attachments WHERE case_id = :TEMP__CASE_ID
)
SELECT PG_SIZE_PRETTY(SUM(s)) AS size
FROM temp__sizes;""")

    ############################################################################
    # LogicHub -> Integrations

    def clipboard_integration_files_path_logichub_host(self):
        self.write_clipboard("/var/lib/docker/volumes/logichub_data/_data/shared/integrationsFiles/")

    def clipboard_integration_files_path_logichub_host_from_file_name(self):
        self.write_clipboard(
            "/var/lib/docker/volumes/logichub_data/_data/shared/integrationsFiles/{}".format(self.read_clipboard()))

    def clipboard_integration_files_path_integration_containers(self):
        self.write_clipboard("/opt/files/shared/integrationsFiles/")

    def clipboard_integration_files_path_integration_containers_from_file_name(self):
        self.write_clipboard("/opt/files/shared/integrationsFiles/{}".format(self.read_clipboard()))

    def clipboard_integrationsFiles_path_service_container(self):
        self.write_clipboard("/opt/docker/data/shared/integrationsFiles/")

    def clipboard_integrationsFiles_path_service_container_from_file_name(self):
        self.write_clipboard("/opt/docker/data/shared/integrationsFiles/{}".format(self.read_clipboard()))

    ############################################################################
    # LogicHub -> LogicHub Upgrades

    def logichub_upgrade_prep_verifications(self):
        """
        Upgrade Prep: Visual inspection

        :return:
        """
        self.copy_file_contents_to_clipboard(self.config.dir_supporting_scripts, "upgrade_prep-verify.sh")

    def logichub_upgrade_prep_backups(self):
        """
        Upgrade Prep: Backups

        :return:
        """
        self.copy_file_contents_to_clipboard(self.config.dir_supporting_scripts, "upgrade_prep-backups.sh")

    def logichub_upgrade_prep_backups_lite(self):
        """
        Upgrade Prep: Backups (lightweight version)

        :return:
        """
        file_name = "upgrade_prep-backups.sh"
        file_path = os.path.join(self.config.dir_supporting_scripts, file_name)
        if not os.path.isfile(file_path):
            self.display_notification_error("Invalid path to supporting script")
        with open(file_path, "rU") as f:
            output = f.read()

        output = output.replace('run_backups "$@"', 'run_backups --no-logs --no-lh-backup')
        self.write_clipboard(output)

    def logichub_upgrade_prep_backups_skip_logs(self):
        """
        Upgrade Prep: Backups (skip logs)

        :return:
        """
        file_name = "upgrade_prep-backups.sh"
        file_path = os.path.join(self.config.dir_supporting_scripts, file_name)
        if not os.path.isfile(file_path):
            self.display_notification_error("Invalid path to supporting script")
        with open(file_path, "rU") as f:
            output = f.read()

        output = output.replace('run_backups "$@"', 'run_backups --no-logs')
        self.write_clipboard(output)

    def logichub_upgrade_command_from_clipboard(self):
        """
        Upgrade Command (from milestone version in clipboard)

        :return:
        """
        _input_str = self.read_clipboard(trim_input=True, lower=True)
        cmd = self.make_upgrade_command(_input_str)
        self.write_clipboard(cmd)

    def logichub_upgrade_command_static(self):
        """
        Upgrade Command (static)

        :return:
        """
        cmd = self.make_upgrade_command()
        self.write_clipboard(cmd)

    def logichub_upgrade_command_from_clipboard_with_backup_script(self):
        """
        Upgrade Command with Backup Script (from milestone version in clipboard)

        :return:
        """
        _input_str = self.read_clipboard(trim_input=True, lower=True)
        cmd = "{}; {}".format(self.make_backup_command(), self.make_upgrade_command(_input_str))
        self.write_clipboard(cmd)

    def logichub_upgrade_command_static_with_backup_script(self):
        """
        Upgrade Command with Backup Script (static)

        :return:
        """
        cmd = "{}; {}".format(self.make_backup_command(), self.make_upgrade_command())
        self.write_clipboard(cmd)

    @staticmethod
    def _fix_json(json_str):
        def run_fix(obj, step_count=None):
            step_count = 0 if step_count is None else step_count + 1
            if type(obj) is bytes:
                raise TypeError("JSON input cannot be bytes")
            if type(obj) is str:
                try:
                    obj = json.loads(obj)
                except (TypeError, json.JSONDecodeError):
                    if step_count:
                        return obj
                    else:
                        raise Exception("Initial input could not be parsed as valid JSON")

            # Loop through all entries in case there are nested dicts or strings.
            if type(obj) in (list, tuple):
                obj = [run_fix(entry, step_count=step_count) for entry in obj]
            elif isinstance(obj, dict):
                obj = {k: run_fix(obj[k], step_count=step_count) for k in obj.keys()}
            return obj

        return run_fix(json_str)

    def _sort_dicts_and_lists(self, input_value):
        """Sort dicts and lists recursively with a self-calling function"""
        _output = input_value
        # If the object is not a list or a dict, just return the value
        if type(_output) not in (list, dict):
            return _output
        if isinstance(_output, dict):
            # Crawl and sort dict values before sorting the dict itself
            _output = {k: self._sort_dicts_and_lists(v) for k, v in _output.items()}
            # Sort dict by keys
            _output = {k: _output[k] for k in sorted(_output.keys())}
        elif isinstance(_output, list):
            # Crawl and sort list values before sorting the list itself
            _output = [self._sort_dicts_and_lists(val) for val in _output]
            try:
                # Try to simply sort the list (will fail if entries are dicts or nested lists)
                _output = sorted(_output)
            except TypeError:
                # Map string versions of entries to their real values
                temp_map_input_as_strings = {}
                for k in _output:
                    try:
                        temp_map_input_as_strings[json.dumps(k)] = k
                    except KeyError:
                        temp_map_input_as_strings[str(k)] = k

                # Sort real values by their string versions
                _output = [temp_map_input_as_strings[k] for k in sorted(temp_map_input_as_strings.keys())]
        return _output

    def _process_json_clipboard(
            self, sort_output=None, format_output=False, fix_output=False,
            compact_spacing=False, format_auto=False, return_obj=False):
        """
        One method to standardize reading JSON from the clipboard, processing as needed, and updating the clipboard

        :param sort_output: Sort by keys and values
        :param format_output: Format JSON output with line breaks and indentation instead of a single line
        :param fix_output: Fix values where dicts or lists are stored as escaped strings
        :param compact_spacing: When converting JSON to a compact string, make it semi-compact (i.e. still include spaces after colons and commas)
        :param format_auto: If set to True, override "format_output" and check whether there are line breaks in the clipboard input and set format_output automatically
        :return:
        """

        # Read clipboard, convert from JSON
        json_loaded = self._json_notify_and_exit_when_invalid()

        # If fix_output is enabled, crawl for dicts or lists stored as escaped strings
        if fix_output:
            json_loaded = self._fix_json(json_loaded)

        # If sort_output is enabled, sort recursively by keys and values
        if sort_output:
            if sort_output == "values":
                json_loaded = Reusable.sort_dict_by_values(json_loaded)
            elif sort_output == "values_reversed":
                json_loaded = Reusable.sort_dict_by_values(json_loaded, reverse=True)
            else:
                json_loaded = self._sort_dicts_and_lists(json_loaded)

        if format_auto:
            # If there are newlines in the clipboard, assume that it is formatted JSON
            # If no newlines, then return compact JSON
            if '\n' in self.read_clipboard():
                format_output = True
                compact_spacing = True
            else:
                format_output = False

        if return_obj:
            return json_loaded

        if format_output is True:
            # Format output with line breaks and indentation
            _output = json.dumps(json_loaded, ensure_ascii=False, indent=2)
        else:
            separators = (', ', ': ') if compact_spacing is True else (',', ':')
            # Format output as a compact string on a single line
            _output = json.dumps(json_loaded, ensure_ascii=False, separators=separators)

        self.write_clipboard(_output)

    def _json_notify_and_exit_when_invalid(self, manual_input=None):
        """
        Reusable script to validate that what is in the clipboard is valid JSON,
        and raise an alert and exit if it is not.

        :return:
        """
        if manual_input:
            _input_str = manual_input
        else:
            _input_str = self.read_clipboard()
        if _input_str.endswith('%'):
            _input_str = _input_str[:-1]
        try:
            new = json.loads(_input_str, strict=False)
            for _try in range(5):
                if isinstance(new, (dict, list)):
                    break
                new = json.loads(new, strict=False)
            json_dict = new
        except ValueError:
            json_dict = None

        if not json_dict or not isinstance(json_dict, (dict, list)):
            self.display_notification_error('Invalid JSON !!!!!!!!!!')
            sys.exit(1)
        else:
            return json_dict

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
