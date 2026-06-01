#!/usr/bin/env php
<?php
declare(strict_types=1);

$event = $argv[1] ?? 'info';
$severity = (int)($argv[2] ?? 4);
$subject = $argv[3] ?? 'LoxBerry Host Backup';
$message = $argv[4] ?? '';
$logfile = $argv[5] ?? '';
$recipient = trim($argv[6] ?? '');

function hostbackup_const_or_default(string $name, string $fallback): string
{
    return defined($name) ? (string)constant($name) : $fallback;
}

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

function hostbackup_read_mail_config(): array
{
    $path = hostbackup_const_or_default('LBSCONFIGDIR', '/opt/loxberry/config/system') . '/mail.json';
    if (!is_readable($path)) {
        return [];
    }

    $data = json_decode((string)file_get_contents($path), true);
    return is_array($data) ? $data : [];
}

function hostbackup_mail_enabled(array $config): bool
{
    return hostbackup_is_enabled($config['SMTP']['ACTIVATE_MAIL'] ?? 0)
        && hostbackup_is_enabled($config['NOTIFICATION']['MAIL_PLUGIN_INFOS'] ?? 1);
}

function hostbackup_is_enabled($value): bool
{
    if (is_bool($value)) {
        return $value;
    }

    return in_array(strtolower((string)$value), ['1', 'true', 'yes', 'on'], true);
}

function hostbackup_default_recipient(array $config): string
{
    return trim((string)($config['SMTP']['EMAIL'] ?? ''));
}

function hostbackup_mime_header(string $value): string
{
    return '=?UTF-8?B?' . base64_encode($value) . '?=';
}

function hostbackup_sendmail_path(): string
{
    foreach (['/usr/sbin/sendmail', '/usr/lib/sendmail', '/sbin/sendmail'] as $path) {
        if (is_executable($path)) {
            return $path;
        }
    }

    return 'sendmail';
}

function hostbackup_send_success_mail_only(string $subject, string $message, string $logfile, string $recipient): void
{
    $config = hostbackup_read_mail_config();
    if (!hostbackup_mail_enabled($config)) {
        exit(0);
    }

    $to = $recipient !== '' ? $recipient : hostbackup_default_recipient($config);
    if ($to === '') {
        exit(0);
    }

    if (!filter_var($to, FILTER_VALIDATE_EMAIL)) {
        fwrite(STDERR, "invalid mail recipient\n");
        exit(3);
    }

    $from = hostbackup_default_recipient($config);
    if ($from === '' || !filter_var($from, FILTER_VALIDATE_EMAIL)) {
        $from = $to;
    }

    $body = $message;
    if ($logfile !== '') {
        $body .= "\n\nLogfile: " . $logfile;
    }

    $mail = [
        'To: ' . $to,
        'From: LoxBerry Host Backup <' . $from . '>',
        'Subject: ' . hostbackup_mime_header($subject),
        'MIME-Version: 1.0',
        'Content-Type: text/plain; charset=UTF-8',
        'Content-Transfer-Encoding: 8bit',
        '',
        $body,
        '',
    ];

    $descriptorSpec = [
        0 => ['pipe', 'r'],
        1 => ['pipe', 'w'],
        2 => ['pipe', 'w'],
    ];

    $process = proc_open(hostbackup_sendmail_path() . ' -t -oi', $descriptorSpec, $pipes);
    if (!is_resource($process)) {
        fwrite(STDERR, "sendmail could not be started\n");
        exit(4);
    }

    fwrite($pipes[0], implode("\n", $mail));
    fclose($pipes[0]);
    $stdout = stream_get_contents($pipes[1]);
    $stderr = stream_get_contents($pipes[2]);
    fclose($pipes[1]);
    fclose($pipes[2]);
    $status = proc_close($process);

    if ($status !== 0) {
        fwrite(STDERR, trim($stderr !== '' ? $stderr : $stdout) . "\n");
        exit($status);
    }

    exit(0);
}

hostbackup_include_loxberry_lib('loxberry_system.php');

if ($event === 'success') {
    hostbackup_send_success_mail_only($subject, $message, $logfile, $recipient);
}

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
