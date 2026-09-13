package LoxBerry::Web;
use strict;
use warnings;
sub import {}
# Exercise the CGI's own head additions. The generic Perl stub does not render
# a document, and manually injecting asset links would hide delivery regressions.
sub lbheader {
    print '<!doctype html><html><head><meta charset="utf-8">';
    print '<style>body { background: #f7f7f7; } strong, span { letter-spacing: normal; }</style>';
    print $main::htmlhead || '';
    print '</head><body>';
}
sub lbfooter { print '</body></html>'; }
1;
