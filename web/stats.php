<?php
ini_set('display_errors', 1);
ini_set('display_startup_errors', 1);
error_reporting(E_ALL);

  $which_sites = isset($_GET['sites']) ? $_GET['sites'] : 'good';

  $table = 'stats';
  $db = new SQLite3('stats.db');

  if($which_sites == 'all') {
    $results = $db->query('SELECT * FROM ' . $table . 
                          ' INNER JOIN sites on sites.site = ' . $table . 
                          '.site ORDER BY site');
  } else {

    $isgood = ($which_sites == 'need_checked' || $which_sites == 'bad') ? '0' : '1';
    $results = $db->query('SELECT * FROM ' . $table .
                          ' INNER JOIN sites on sites.site = ' . $table . 
                          '.site WHERE isgood = ' . $isgood . ' ORDER BY site');

  }

  include 'output.html';

  $db = null;
?>
