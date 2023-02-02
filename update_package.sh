#!/usr/bin/env bash

set -Eeuo pipefail
trap cleanup SIGINT SIGTERM ERR EXIT

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd -P)

usage() {
  cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}")

This is a tool for the Lazy developer
checks direct dependency minor version updates
If you say yes it will update it do drush updb, drush cex and commit the changes for you :D
in format: Update package_name (old_version => new_version)

Available options:

-h, --help      Print this help and exit
-v, --verbose   Print script debug info
EOF
  exit
}

cleanup() {
  trap - SIGINT SIGTERM ERR EXIT
  # script cleanup here
}

setup_colors() {
  if [[ -t 2 ]] && [[ -z "${NO_COLOR-}" ]] && [[ "${TERM-}" != "dumb" ]]; then
    NOFORMAT='\033[0m' RED='\033[0;31m' GREEN='\033[0;32m' ORANGE='\033[0;33m' BLUE='\033[0;34m' PURPLE='\033[0;35m' CYAN='\033[0;36m' YELLOW='\033[1;33m'
  else
    NOFORMAT='' RED='' GREEN='' ORANGE='' BLUE='' PURPLE='' CYAN='' YELLOW=''
  fi
}

msg() {
  echo >&2 -e "${1-}"
}

die() {
  local msg=$1
  local code=${2-1} # default exit status 1
  msg "$msg"
  exit "$code"
}

parse_params() {
  # default values of variables set from params
  flag=0
  param=''

  while :; do
    case "${1-}" in
    -h | --help) usage ;;
    -v | --verbose) set -x ;;
    --no-color) NO_COLOR=1 ;;
    -f | --flag) flag=1 ;; # example flag
    -p | --param) # example named parameter
      param="${2-}"
      shift
      ;;
    -?*) die "Unknown option: $1" ;;
    *) break ;;
    esac
    shift
  done

  args=("$@")

  # check required params and arguments
#  [[ -z "${param-}" ]] && die "Missing required parameter: param"
#  [[ ${#args[@]} -eq 0 ]] && die "Missing script arguments"

  return 0
}

parse_params "$@"
setup_colors

# script logic here

do_stuff () {
  library_name=$1
  package_name=$2

  info=`composer outdated -m "$library_name/$package_name"`
  current=`echo "$info" | sed -n '/versions/s/^[^0-9]\+\([^,]\+\).*$/\1/p'`
  available=`echo "$info" | sed -n '/latest/s/^[^0-9]\+\([^,]\+\).*$/\1/p'`
  url=`echo "$info" | grep "homepage : "`
  version=`echo "$info"| grep "source   :"`

  if [ "$current" = "$available" ]; then
    msg "On latest version"
    exit 1
  fi
  msg "Current version $current"
  msg "Available version ${YELLOW}$available${NOFORMAT}"

  msg "Please check the release logs for any ${RED}breaking changes"
  msg "${url:9}/releases/${version##* }"
  read -p "Are you 100% sure ? Update (y/n) ?" </dev/tty yn
  msg ${NOFORMAT}

  case $yn in
  	y ) msg ok, we will proceed
      echo `composer update "drupal/$package_name" --with-dependencies`
      msg "Updated to $available"
      # ToDo might want to prompt user to take a look at the changes ?

      drush updb -y
      drush cex -y
      #sh ./cex-nocrap.sh # Úse the nocrap so i dont have to do the config manually :P
      drush cr
      git add composer.lock
      # disabled cause domains config
      # ToDo add only changes from drush cex ?
      #git add config/sync/
      # There might be git hooks that use lando grumphp -- need to deal with it ?
      git commit -m "Update $package_name ($current => $available)" --no-verify;;
  	n ) msg skipping...;;
  	* ) msg invalid response skipping;
  	  return 1;;

  esac
}


read -p "Please enter library name [drupal]:" library
library_name=${library:-drupal}
read -p "check every package ? ([y]/n)" update
update_all=${library:-y}
#ToDO use the library name ?
case $update_all in
	y ) msg ok, we will proceed;
      composer outdated drupal/* --direct --minor-only | \
      while read i
      do
        IFS=', ' read -r -a array <<< "$i"
        IFS='/' read -ra ADDR <<< "${array[0]}"
        if [[ "${ADDR[1]}" == *"core"* ]]; then
          msg "we skipping core"
          continue
        fi
        if [[ "${ADDR[1]}" == *"graph_api"* ]]; then
          msg "we skipping graph_api"
          continue
        fi
        if [[ "${ADDR[1]}" == *"elasticsearch_helper_views"* ]]; then
          msg "we skipping elasticsearch_helper_views"
          continue
        fi

        echo ""
        msg "Now checking: ${ADDR[0]} ${ADDR[1]}"
        do_stuff ${ADDR[0]} ${ADDR[1]}
      done;
      exit 0;;
	n ) read -p "Please enter package name " package_name;
	  do_stuff $library_name $package_name;;

	* ) echo invalid response;
		exit 1;;
esac
