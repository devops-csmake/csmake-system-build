# <copyright>
# (c) Copyright 2026 Autumn Patterson
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# </copyright>
"""Shared test doubles: a recording stand-in for the csmake log, and a
directory of fake executables (sudo, losetup, lvs, ...) that goes first on
PATH so modules that shell out run against known output and never touch
real devices."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock


# A SystemBuild 'filesystem' entry: mountpoint -> (mountpoint, device, type,
# fstab-id), deliberately not in mount order.
SAMPLE_FILESYSTEM = {
    '/home':     ('/home', '/dev/loop3p4', 'ext4', 'LABEL=home'),
    '/boot/efi': ('/boot/efi', '/dev/loop3p1', 'vfat', 'LABEL=efi'),
    '/':         ('/', '/dev/loop3p3', 'ext4', 'LABEL=root'),
    '/boot':     ('/boot', '/dev/loop3p2', 'ext2', 'LABEL=boot'),
}


def read_bytes(path):
    with open(path, 'rb') as handle:
        return handle.read()


class FakeLog:
    """Records every log call; out()/err() are real subprocess sinks."""

    def __init__(self):
        self.records = []
        self.results = []

    def out(self):
        return subprocess.DEVNULL

    def err(self):
        return subprocess.DEVNULL

    def passed(self):
        self.results.append('passed')

    def failed(self):
        self.results.append('failed')

    def __getattr__(self, level):
        if level.startswith('__'):
            raise AttributeError(level)

        def record(msg, *args, **kwargs):
            try:
                text = msg % args if args else msg
            except (TypeError, ValueError):
                # Some modules hand the logger mismatched format args
                text = '%s %r' % (msg, args)
            self.records.append((level, text))
        return record

    def messages(self, level):
        return [text for lvl, text in self.records if lvl == level]


class FakeBin:
    """Fake executables in a temp dir that is prepended to PATH.

    Every fake appends its argv to a shared call log, prints canned stdout
    and exits with a canned status.  The 'sudo' fake never runs a real
    command: it runs the fake of that name if there is one, otherwise it
    just records the call and succeeds.
    """

    def __init__(self, test):
        self.dir = tempfile.mkdtemp(prefix='fakebin')
        test.addCleanup(shutil.rmtree, self.dir, True)
        self.log = os.path.join(self.dir, 'calls.log')
        open(self.log, 'w').close()
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        test.addCleanup(patcher.stop)
        os.environ['PATH'] = self.dir + os.pathsep + os.environ.get('PATH', '')
        self._write('sudo', """#!/bin/sh
cmd="$1"
shift
if [ -x '%(dir)s'/"$cmd" ]; then
    exec '%(dir)s'/"$cmd" "$@"
fi
{ printf '%%s' "$cmd"; for a in "$@"; do printf '\\t%%s' "$a"; done; printf '\\n'; } >> '%(log)s'
exit 0
""" % {'dir': self.dir, 'log': self.log})

    def _write(self, name, body):
        path = os.path.join(self.dir, name)
        with open(path, 'w') as script:
            script.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def add(self, name, stdout='', rc=0, extra=''):
        """Install fake <name>.  stdout is printed exactly; extra is
        shell run (with the original "$@") before the output."""
        datafile = os.path.join(self.dir, name + '.stdout')
        with open(datafile, 'w') as data:
            data.write(stdout)
        self._write(name, """#!/bin/sh
{ printf '%%s' '%(name)s'; for a in "$@"; do printf '\\t%%s' "$a"; done; printf '\\n'; } >> '%(log)s'
%(extra)s
cat '%(data)s'
exit %(rc)d
""" % {'name': name, 'log': self.log, 'extra': extra,
       'data': datafile, 'rc': rc})

    def calls(self, name=None):
        """List of argv lists (command name first), optionally for one name."""
        with open(self.log) as log:
            calls = [line.rstrip('\n').split('\t') for line in log if line.strip()]
        if name is not None:
            calls = [call for call in calls if call[0] == name]
        return calls


class FakeBinTestCase(unittest.TestCase):
    """Convenience: self.bin is a FakeBin, self.tmp a scratch directory."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='sbtest')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = FakeBin(self)
        self.log = FakeLog()
