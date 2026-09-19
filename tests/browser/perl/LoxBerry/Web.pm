package LoxBerry::Web;
use strict;
use warnings;
sub import {}
# Exercise the CGI's own head additions. The generic Perl stub does not render
# a document, and manually injecting asset links would hide delivery regressions.
sub lbheader {
    print '<!doctype html><html><head><meta charset="utf-8">';
    # LoxBerry 4.0.0.15 main.css (50cfa335): legacy .wide is a typography class,
    # not a layout utility. Keep the desktop/mobile declarations which caused
    # inheritance in the plugin; this is not a complete device-theme fixture.
    print '<style>body { background: #f7f7f7; } strong, span { letter-spacing: normal; } .wide { font-size: calc(14px + 1.3vw); letter-spacing: 0.10em; text-align: left; vertical-align: middle; border-bottom: 2px ridge #cdcdcd; padding: 7px; padding-top: 1px; margin-top: 0px; font-weight: bold; } @media (max-width: 600px) { .wide { font-size: calc(12px + 1vw); letter-spacing: 0.05em; word-break: break-word; } }</style>';
    print $main::htmlhead || '';
    print '</head><body>';
}
sub lbfooter { print '</body></html>'; }
1;
