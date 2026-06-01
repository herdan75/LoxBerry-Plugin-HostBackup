#!/usr/bin/env php
<?php
declare(strict_types=1);

$event = $argv[1] ?? 'info';
$severity = (int)($argv[2] ?? 4);
$subject = $argv[3] ?? 'LoxBerry Host Backup';
$message = $argv[4] ?? '';
$logfile = $argv[5] ?? '';
$recipient = trim($argv[6] ?? '');

function hostbackup_include_loxberry_lib(string $file): void
{
    if (function_exists('notify_ext') && $file === 'loxberry_log.php') {
        return;
    }

    $candidates = [
        $file,
        '/opt/loxberry/libs/phplib/' . $file,
        '/opt/loxberry/libs/php/' . $file,
    ];

    foreach ($candidates as $candidate) {
        if (@include_once($candidate)) {
            return;
        }
    }
}

hostbackup_include_loxberry_lib('loxberry_system.php');
hostbackup_include_loxberry_lib('loxberry_log.php');

if (!function_exists('notify_ext')) {
    fwrite(STDERR, "notify_ext not available\n");
    exit(2);
}

$notification = [
    'PACKAGE' => 'loxberryhostbackup',
    'NAME' => $subject,
    'MESSAGE' => $message,
    'SEVERITY' => $severity,
];

if ($logfile !== '') {
    $notification['LOGFILE'] = $logfile;
}

if ($recipient !== '') {
    $notification['EMAIL'] = $recipient;
}

notify_ext($notification);
exit(0);
