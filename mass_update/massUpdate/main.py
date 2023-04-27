import argparse
import fnmatch
import json
import os
import sys
import tempfile
import subprocess
import threading
import time

from github import Github
from git import Repo
from packaging.version import Version
from dotenv import load_dotenv

import yaml

# Constants.
load_dotenv()
api_token = os.environ["GH_TOKEN"]
github_account = os.environ["GH_ACCOUNT"]
modules = {
    "wunderio/updates_log": "2.1",
    "drupal/monolog": "2.1",
}
branch_name = os.environ["BRANCH"]


def is_version_greater_or_equal(current_version, min_version):
    """"Check if current version is greater or equal to min version"""
    return Version(current_version) >= Version(min_version)


def get_package_versions(composer_lock_path: str, module_names: list) -> dict:
    """ Get package versions from composer lock file. """
    with open(composer_lock_path) as file:
        composer_lock = json.load(file)

    package_versions = {}
    for package in composer_lock.get("packages", []):
        if package["name"] in module_names:
            package_versions[package["name"]] = package["version"]
            if len(package_versions) == len(module_names):
                break
    return package_versions


def check_versions():
    """ Check if all required packages are installed to min required version. """
    modules_to_require = []
    module_names = list(modules.keys())
    composer_lock_path = os.path.join(temp_dir, "composer.lock")
    # ToDo handle "weird" composer.lock file locations.
    if os.path.exists(composer_lock_path):
        current_versions = get_package_versions(composer_lock_path, module_names)
        for module_name, min_version in modules.items():
            current_version = current_versions.get(module_name)
            if current_version and is_version_greater_or_equal(current_version, min_version):
                print(f"Skipping {module_name}: Current version {current_version} >= minimum version {min_version}")
                continue
            else:
                modules_to_require.append(module_name)
    else:
        print(f"No composer.lock file found at {composer_lock_path}")
    return modules_to_require


def do_upgrade(modules_to_require):
    """Require the latest version of each module and do a commit."""
    for module_name, min_version in modules.items():
        if module_name in modules_to_require:
            print(f"requiring {module_name} to {min_version}")
            run_command_with_loading_message(
                ["composer", "require", f"{module_name}:^{min_version}", "--ignore-platform-reqs", '-w'], temp_dir)
            local_repo.git.add("composer.json", "composer.lock")
            # Bypass GrumPHP checks.
            local_repo.git.commit("-m", f"Update {module_name} to minimum version {min_version}", "-n")


def get_confirm(message):
    """Get confirmation from user"""
    if not args.skip_confirmation:
        return input(f"{message} (Y/N)").lower() == "y"
    else:
        return True


def generate_pull_request(repo, options):
    """Create the pull request."""
    pr_title = f"Updates log automated pull request"
    repo.create_pull(title=pr_title, head=branch_name, base=repo.default_branch, body=options['body'])


def deal_with_settings(dir: str) -> str:
    """Handle configuration [core.extension.yml, settings.php]"""
    msg = ''
    existing = get_package_versions(os.path.join(temp_dir, "composer.lock"),
                                    ["drupal/config_split", "drupal/ultimate_cron"])
    config_split = existing.get("drupal/config_split", 0)
    ultimate_cron = existing.get("drupal/ultimate_cron", 0)


    if ultimate_cron != 0:
        msg = f"- `ultimate_cron` detected in `composer.lock`, please add ultimate_cron jobs for updates_log \n"
    if config_split != 0:
        msg += "- Config split found in composer.lock, please enable updates_log in prod environment. \n"
        return msg

    # Enable modules in core.extension if we can.
    core_extension_path = find_file("core.extension.yml", dir)
    enabled_modules = []
    if core_extension_path is not None:
        path = os.path.join(dir, core_extension_path)
        enabled_modules = update_module_list(path, ['updates_log', 'monolog'])
    if enabled_modules:
        local_repo.git.add(core_extension_path)
        # Bypass GrumPHP checks.
        local_repo.git.commit("-m", f"Enable Updates_log and monolog in core.extension.yml", "-n")
        msg = f"- Enabled `{enabled_modules}` in core.extension.yml \n"

    file_path = os.path.join(dir, "web/sites/default/settings.php")
    line_before_switch = "$settings['updates_log_disabled'] = TRUE;"
    line_in_case = "$settings['updates_log_disabled'] = FALSE;"

    # Try to modify settings.php.
    args = ["./insert_lines.sh", file_path, line_before_switch, line_in_case]
    result = subprocess.run(args, capture_output=True, text=True)

    if result.returncode == 0:
        msg += "- Updates_log Has been Enabled in settings.php in Prod env only \n"
        local_repo.git.add("web/sites/default/settings.php")
        local_repo.git.commit("-m", f"Enable Updates_log in PROD only", "-n")
    else:
        msg = f"- Could not automatically add `$settings['updates_log_disabled']` to settings.php \n"

    return msg


def generate_pull_request_body(settings: dict) -> str:
    """Generate the body of the pull request."""
    pr_template = f"""
## Summary

This PR Adds/updates `wunderio/updates_log` and `drupal/monolog` to the minimum required versions of 2.1:
THIS is done via a AUTOMATIC SCRIPT
**NB  Please check the code carefully before merging**

## Changes

- Updated `composer.json` and `composer.lock` to include the new minimum required versions for the modules.
{settings['exceptions']}

## Rationale

Updates_log is going to replace Warden in our projects Helping us get alerts and info about the state of modules 
in our projects


## Next Steps

- Disable dbLog module if you have it enabled.
- If you use `ultimate_cron` you need to add cron jobs for `updates_log`.
- If you want enable updates_log in your main env also ( this can be done with settings.php)
- Create and setup sumologic searches and alerts  [Intra docs](https://intra.wunder.io/info/security-notification-integrations/mission-4-5xx-notifications-security-notifications-drupal)
- Mark in the Dashboard when done

## TESTING

ssh into the shell container and check that updates_log is enabled.
`drush pml | grep updates_log`
    if not enabled ( E.g. you use config_split ) then enable the module for testing.
    `drush en updates_log`

IF used without config_split and `$settings['updates_log_disabled'] = TRUE` is used in `settings.php`
then no output should be generated.
run `drush cron`
check that no "updates_log.INFO" message is generated in the shell output.


now run `UPDATES_LOG_TEST=1 drush cron` ( This bypasses the Time checks and the "disabled" check)
check that the "statistics" are generated in the shell output. (updates_log.INFO: updates_log_statistics=...)

## Additional Notes

Env url: {settings['env']['url']}
ssh: 
```
{settings['env']['ssh']}
```
[UpdatesLog docs](https://github.com/wunderio/drupal-updates-log)
[Monolog docs](https://git.drupalcode.org/project/monolog)
[Updates_log implementation dashboard](https://docs.google.com/spreadsheets/d/1fZVwWgRAe2RisCgkaJdjqrzW25yV7-IQx9XN1oAc7X0/edit#gid=0)
    """
    return pr_template


def read_property_from_yaml(file_path, property_name):
    """Get Property from YAML file"""
    with open(file_path, "r") as file:
        content = yaml.safe_load(file)

    return content.get(property_name, None)


def update_module_list(yaml_file_path, module_list):
    """Enable modules in core.extension.yml if they are not already enabled"""
    with open(yaml_file_path, "r") as f:
        content = yaml.safe_load(f)

    modules = content.get("module", {})
    added_modules = []

    for module_name in module_list:
        if module_name not in modules:
            modules[module_name] = 0
            added_modules.append(module_name)

    # Sort the modules by value and then alphabetically
    sorted_modules = {k: v for k, v in sorted(modules.items(), key=lambda item: (item[1], item[0]))}

    content["module"] = sorted_modules

    with open(yaml_file_path, "w") as f:
        yaml.safe_dump(content, f, sort_keys=False, allow_unicode=True)

    return added_modules


def find_file(file_name, base_dir=".", search_dirs=None, max_depth=2, excluded_dirs=None, relative=True):
    """
    Find the specified file in the given search directories or up to a maximum depth from the base directory,
    excluding specified directories from the search. Returns the relative or absolute path of the found file.

    Args:
    file_name (str): The name of the file to search for.
    base_dir (str, optional): The base directory from which to start the search. Defaults to ".".
    search_dirs (Optional[List[str]]): A list of directories to search in first. Defaults to ["config/sync", "sync"].
    max_depth (int, optional): The maximum depth to search from the base directory. Defaults to 2.
    excluded_dirs (Optional[List[str]]): A list of directory names to exclude from the search. Defaults to None.
    relative (bool, optional): Whether to return the relative path of the found file. Defaults to True.

    Returns:
    str: The path of the found file, either relative or absolute, or None if the file is not found.
    """
    if search_dirs is None:
        search_dirs = ["config/sync", "sync"]
    if excluded_dirs is None:
        excluded_dirs = ["vendor"]

    # Search for the file in the specified directories
    for search_dir in search_dirs:
        for root, _, filenames in os.walk(os.path.join(base_dir, search_dir), topdown=True):
            for filename in fnmatch.filter(filenames, file_name):
                found_path = os.path.join(root, filename)
                return os.path.relpath(found_path, base_dir) if relative else found_path

    # If not found in the specified directories, search up to max_depth levels deep
    for root, dirs, filenames in os.walk(base_dir, topdown=True):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if d not in excluded_dirs]

        level = root.count(os.sep) - base_dir.count(os.sep)
        if level <= max_depth:
            for filename in fnmatch.filter(filenames, file_name):
                found_path = os.path.join(root, filename)
                return os.path.relpath(found_path, base_dir) if relative else found_path

    # If the file is not found, return None
    return None


def run_command_with_loading_message(command, cwd, ):
    """Hides command output and shows loading message"""

    def show_loading_message():
        """Show loading message"""
        loading_symbols = ["|", "/", "-", "\\"]
        i = 0
        while not done_loading:
            sys.stdout.write("\r" + message + " " + loading_symbols[i % len(loading_symbols)])
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1

    message = f"Executing: {' '.join(command)}"
    # print(message)

    # Set this flag to True when the command process is complete
    done_loading = False

    # Start the loading message in a separate thread
    loading_thread = threading.Thread(target=show_loading_message)
    loading_thread.start()

    # Run the command
    process = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=cwd, check=True)

    # Stop the loading message
    done_loading = True
    loading_thread.join()

    # Clear the loading message and show a completion message
    sys.stdout.write("\r" + " " * (len(message) + 5) + "\r")
    sys.stdout.flush()

    if process.returncode == 0:
        print(f"{message} - Done")
    else:
        print(f"{message} - Failed")


def get_env_data(temp_dir, repo_name):
    """Get env data for links"""

    try:
        silta_yaml = find_file('silta.yml', temp_dir, ['silta'])
        path = os.path.join(temp_dir, silta_yaml)
        project_name = read_property_from_yaml(path, 'projectName')
        b_name = branch_name.replace('_', '-')
        if not project_name:
            p_name = repo_name
        else:
            p_name = project_name.replace(' ', '-').lower()
        url = "https://" + b_name + "." + p_name + os.environ['ENV_SUFFIX']
        ssh = "ssh www-admin@" + b_name + "-shell." + repo_name + " -J www-admin@ssh" + os.environ[
            'ENV_SUFFIX']
    except Exception as e:
        print(e)
        url = ''
        ssh = ''
    return {'url': url, 'ssh': ssh}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip_confirmation", action="store_true", help="Skip confirmation prompt")
    # parser.add_argument("repo_names_file", help="File with repository names")
    args = parser.parse_args()

    repo_names_file = "names.txt"  # args.repo_names_file
    g = Github(api_token)
    user = g.get_user()

    with open(repo_names_file, "r") as f:
        for repo_name in f:
            repo_name = repo_name.strip()
            print(f"Processing {repo_name}")
            if not get_confirm("Are you sure you want to continue?"):
                print(f"Canceled {repo_name} continuing")
                continue

            repo = g.get_repo(f"{github_account}/{repo_name}")

            # Clone the repo
            # This removes the dir after NB Indentation.
            with tempfile.TemporaryDirectory(dir="tmps/.") as temp_dir:
                # temp_dir = tempfile.mkdtemp(dir="tmps/.")
                run_command_with_loading_message(["git", "clone", repo.ssh_url, temp_dir], None)
                local_repo = Repo(temp_dir)

                # Create a new branch locally
                try:
                    local_repo.git.checkout("-b", branch_name)
                except Exception as e:
                    print(f"Git checkout error: {e}")
                    continue
                # testing bypass check
                # install_modules = list(modules.keys())
                install_modules = check_versions()

                if not install_modules:
                    print(f"Modules up to date")
                    continue
                # unless we want to run this in lando (would make it alot slower)
                # we need to ignore platform requirements.
                run_command_with_loading_message(["composer", "install", "--ignore-platform-reqs"], temp_dir)
                do_upgrade(install_modules)
                settings = {"exceptions": deal_with_settings(temp_dir),
                            'env': get_env_data(temp_dir, repo_name)}
                options = {
                    "body": generate_pull_request_body(settings),
                }
                if not get_confirm(f"Are you sure you want to PUSH? ({repo_name}/{branch_name})"):
                    continue
                local_repo.git.push("--set-upstream", "origin", branch_name)
                print(f"Pushed {repo_name} to {branch_name}")
                if not get_confirm("Create a PR?"):
                    continue
                print(f"Generating Pull request...")
                generate_pull_request(repo, options)

    print("Done")
