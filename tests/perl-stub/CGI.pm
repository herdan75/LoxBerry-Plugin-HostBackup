package CGI;
use strict;
use warnings;
use Exporter 'import';
our @EXPORT = qw(escapeHTML header redirect);
our %EXPORT_TAGS = (standard => \@EXPORT);
sub new { return bless {}, shift; }
sub escapeHTML { return defined $_[0] ? $_[0] : ''; }
sub header { return ''; }
sub redirect { return ''; }
sub param { return ''; }
sub upload { return; }
sub request_method { return 'GET'; }
sub url { return './'; }
1;
