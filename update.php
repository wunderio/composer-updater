<?php

function getConfigChanges() {
  $output = shell_exec("drush cst --format=php --fields=name");
  $changes = unserialize($output);
  if (!$changes) {
    return [];
  }
  return array_keys($changes);

}

/**
 * Adds composer.lock and the given config files with `git add`
 * @param array $config_changes
 *
 * @return void
 */
function addFilesToCommit(array $config_changes): void {
  // ToDo get correct dir
  $files = [];
  foreach ($config_changes as $file) {
    $files[] = "config/sync/" . $file . ".yml";
  }
  shell_exec("git add composer.lock " . implode(" ", $files));
}

$composerCheckUpdatesCommand = "composer outdated drupal/* -n -m  -D --locked --no-scripts -vvv";
$updates = shell_exec($composerCheckUpdatesCommand);
$updatesArray = explode("\n", $updates);

if (count($updatesArray) < 1) {
  echo "No updates available.";
  die();
}
echo "The following direct packages have updates available:\n\n";

foreach ($updatesArray as $update) {
  if (!empty($update)) {
    $package = explode(" ", $update)[0];
    echo $package . "\n";
  }
}

$answer = readline("\nDo you want to update these packages? [Y/n] ");

if (strtolower($answer) === 'n') {
  echo "exiting";
  die();
}
foreach ($updatesArray as $update) {
  if (empty($update)) {
    continue;
  }

  $composer_data = explode(" ", preg_replace('/\s+/', ' ',$update));
  // Evil syntax :D
  [$package, $current, , $available] = $composer_data;
  // ToDO this does not work for all version
  $change_log = "https://www.drupal.org/project/".explode('/', $package)[1]."/releases/" . $current;

  echo "Going to update " . $package . " from: " . $current . " to: " . $available . "\n";
  echo "Check for changes here: ";
  echo $change_log . "\n";

  $answer = readline("\nDo you want to continue? [Y/n] ");
  if (strtolower($answer) === 'n') {
    echo "Skipping \n";
    continue;
  }
  if (str_starts_with($package, 'drupal/core-')) {
    //ToDo for Core we need a bit different update eg composer update drupal/core- -W
    echo "skipping core \n";
    continue;
  }
  $updateCommand = "composer update " . $package . " -n -q -w";
  shell_exec($updateCommand);

  $drushCrCommand = "drush cr";
  shell_exec($drushCrCommand);

  $drushUpdbCommand = "drush updb";
  shell_exec($drushUpdbCommand);

  $config_changes = getConfigChanges();
  if (!empty($config_changes)) {
    $cex = shell_exec("drush cex -y");
  }
  addFilesToCommit($config_changes);

  $gitCommitCommand = "git commit -m 'Update " . $package . "' -n";
  shell_exec($gitCommitCommand);

}


