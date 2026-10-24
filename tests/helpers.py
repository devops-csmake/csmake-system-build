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
"""Test doubles shared by the unit tests.

Everything outside the unit under test is mocked: subprocess (sudo, mount,
losetup, lvm, parted, grub ...), os.stat / os.path lookups and glob.  The
subprocess fake honours the real type contract (bytes unless a text mode was
requested) so that bytes-vs-str conversion bugs are still caught.
"""
import os
import stat
import subprocess
import types
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

    def all_text(self):
        return '\n'.join(text for _, text in self.records)


class FakeMapping:
    """Stands in for csmake's FileManager mapping."""

    def __init__(self, specs=(), files=None):
        self.specs = list(specs)
        self.files = list(files) if files is not None else list(specs)

    def iterspecs(self):
        return iter(self.specs)

    def iterfiles(self):
        return iter(self.files)

    def __len__(self):
        return len(self.specs)


def new_module(cls, env=None, log=None, mapping=None, metadata=None, **attrs):
    """Build a real CsmakeModule subclass instance against a fake engine."""
    engine = types.SimpleNamespace(
        settings={'verbose': False, 'debug': False, 'keep-going': False},
        registerBuildExitCallback=mock.Mock(return_value=1),
        unregisterBuildExitCallback=mock.Mock())
    environment = types.SimpleNamespace(
        env=dict(env or {}),
        engine=engine,
        metadata=types.SimpleNamespace(getCurrent=lambda: metadata))
    module = cls(environment, log if log is not None else FakeLog())
    module.mapping = mapping
    for name, value in attrs.items():
        setattr(module, name, value)
    return module


class Call:
    """One recorded subprocess invocation."""

    def __init__(self, func, argv, kwargs):
        self.func = func
        self.argv = argv
        self.kwargs = kwargs

    @property
    def cmd(self):
        """argv without a leading sudo (a str stays a str: shell=True)."""
        if isinstance(self.argv, (list, tuple)):
            argv = list(self.argv)
            return argv[1:] if argv and argv[0] == 'sudo' else argv
        return self.argv

    @property
    def sudo(self):
        return isinstance(self.argv, (list, tuple)) and self.argv[0] == 'sudo'

    def __repr__(self):
        return 'Call(%s, %r)' % (self.func, self.argv)


class _Rule:
    def __init__(self, prefix, rc, stdout, stderr, raises, effect, times):
        self.prefix = prefix
        self.rc = rc
        self.stdout = stdout
        self.stderr = stderr
        self.raises = raises
        self.effect = effect
        self.times = times

    def matches(self, cmd):
        if isinstance(cmd, str):
            return bool(self.prefix) and cmd.startswith(self.prefix[0])
        return list(cmd[:len(self.prefix)]) == list(self.prefix)


def _as_bytes(value):
    return value.encode('utf-8') if isinstance(value, str) else value


class FakeProcess:
    """subprocess.Popen stand-in: communicate() is bytes unless text mode,
    and only returns the streams that were asked for with PIPE."""

    def __init__(self, call, rc, out, err, text):
        self.args = call.argv
        self._kwargs = call.kwargs
        self._rc = rc
        self._out = out
        self._err = err
        self._text = text
        self.returncode = None
        self.pid = 4242

    def communicate(self, input=None, timeout=None):
        if input is not None:
            expected = str if self._text else bytes
            if not isinstance(input, expected):
                raise TypeError('input must be %s' % expected.__name__)
        self.returncode = self._rc
        out = err = None
        if self._kwargs.get('stdout') == subprocess.PIPE:
            out = self._out.decode('utf-8') if self._text else self._out
        if self._kwargs.get('stderr') == subprocess.PIPE:
            err = self._err.decode('utf-8') if self._text else self._err
        return out, err

    def wait(self, timeout=None):
        self.returncode = self._rc
        return self._rc

    def poll(self):
        return self.returncode

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSubprocess:
    """Patches subprocess.call/check_call/check_output/run/Popen.

    Script behaviour with on(*argv_prefix, rc=, stdout=, stderr=, raises=,
    effect=, times=).  A leading 'sudo' is ignored when matching.  The first
    matching rule wins; unmatched commands succeed with no output.  Every
    call is recorded in .calls.
    """

    def __init__(self, test):
        self.calls = []
        self._rules = []
        for name, replacement in (('call', self._call),
                                  ('check_call', self._check_call),
                                  ('check_output', self._check_output),
                                  ('run', self._run),
                                  ('Popen', self._popen)):
            patcher = mock.patch.object(subprocess, name, replacement)
            patcher.start()
            test.addCleanup(patcher.stop)

    # -- scripting ---------------------------------------------------------
    def on(self, *prefix, rc=0, stdout=b'', stderr=b'', raises=None,
           effect=None, times=None):
        self._rules.append(_Rule(prefix, rc, _as_bytes(stdout),
                                 _as_bytes(stderr), raises, effect, times))

    def reset(self):
        """Forget scripted rules and recorded calls."""
        self._rules.clear()
        self.calls.clear()

    # -- inspection --------------------------------------------------------
    def cmds(self, *prefix):
        """Recorded commands (sudo stripped) starting with prefix."""
        return [call.cmd for call in self.calls
                if self._startswith(call.cmd, prefix)]

    def find(self, *prefix):
        return [call for call in self.calls
                if self._startswith(call.cmd, prefix)]

    def all_cmds(self):
        return [call.cmd for call in self.calls]

    @staticmethod
    def _startswith(cmd, prefix):
        if isinstance(cmd, str):
            return bool(prefix) and cmd.startswith(prefix[0])
        return list(cmd[:len(prefix)]) == list(prefix)

    # -- patched entry points ---------------------------------------------
    def _resolve(self, func, argv, kwargs):
        call = Call(func, argv, kwargs)
        self.calls.append(call)
        for rule in reversed(self._rules):   # the latest script wins
            if rule.matches(call.cmd):
                if rule.times is not None:
                    rule.times -= 1
                    if rule.times <= 0:
                        self._rules.remove(rule)
                if rule.effect is not None:
                    rule.effect(call)
                if rule.raises is not None:
                    raise rule.raises
                return call, rule.rc, rule.stdout, rule.stderr
        return call, 0, b'', b''

    @staticmethod
    def _is_text(kwargs):
        return bool(kwargs.get('text') or kwargs.get('universal_newlines')
                    or kwargs.get('encoding') or kwargs.get('errors'))

    def _call(self, args, **kwargs):
        return self._resolve('call', args, kwargs)[1]

    def _check_call(self, args, **kwargs):
        call, rc, _, _ = self._resolve('check_call', args, kwargs)
        if rc != 0:
            raise subprocess.CalledProcessError(rc, args)
        return 0

    def _check_output(self, args, **kwargs):
        if 'stdout' in kwargs:
            raise ValueError('stdout argument not allowed, '
                             'it will be overridden.')
        call, rc, out, err = self._resolve('check_output', args, kwargs)
        if self._is_text(kwargs):
            result = out.decode('utf-8')
        else:
            result = out
        if rc != 0:
            raise subprocess.CalledProcessError(rc, args, output=result)
        return result

    def _run(self, args, **kwargs):
        call, rc, out, err = self._resolve('run', args, kwargs)
        text = self._is_text(kwargs)
        stdout = stderr = None
        if kwargs.get('capture_output') or kwargs.get('stdout') == subprocess.PIPE:
            stdout = out.decode('utf-8') if text else out
        if kwargs.get('capture_output') or kwargs.get('stderr') == subprocess.PIPE:
            stderr = err.decode('utf-8') if text else err
        completed = subprocess.CompletedProcess(args, rc, stdout, stderr)
        if kwargs.get('check') and rc != 0:
            raise subprocess.CalledProcessError(rc, args, stdout, stderr)
        return completed

    def _popen(self, args, **kwargs):
        call, rc, out, err = self._resolve('Popen', args, kwargs)
        return FakeProcess(call, rc, out, err, self._is_text(kwargs))


class FakePaths:
    """Patches os.path.exists / lexists / isdir to answer from a scripted set
    of paths (everything else does not exist).  Paths under real_under (a
    test's own temp dir) are answered by the real functions."""

    def __init__(self, test, exists=(), dirs=(), real_under=None):
        self.exists = set(exists)
        self.dirs = set(dirs)
        self.real_under = real_under
        self._real = {name: getattr(os.path, name)
                      for name in ('exists', 'lexists', 'isdir')}
        for name, answer in (('exists', self._exists),
                             ('lexists', self._lexists),
                             ('isdir', self._isdir)):
            patcher = mock.patch.object(os.path, name, answer)
            patcher.start()
            test.addCleanup(patcher.stop)

    def _is_real(self, path):
        return self.real_under is not None and str(path).startswith(self.real_under)

    def _exists(self, path):
        if self._is_real(path):
            return self._real['exists'](path)
        return path in self.exists or path in self.dirs

    def _lexists(self, path):
        if self._is_real(path):
            return self._real['lexists'](path)
        return path in self.exists or path in self.dirs

    def _isdir(self, path):
        if self._is_real(path):
            return self._real['isdir'](path)
        return path in self.dirs


def fake_stat_result(mode, rdev=0):
    return os.stat_result((mode, 0, 0, 1, 0, 0, 0, 0, 0, 0), {'st_rdev': rdev})


def patch_stat(test, table, real_under=None):
    """Patch os.stat: table maps path -> (st_mode, st_rdev); any other path
    raises FileNotFoundError like the real call.  Paths under real_under are
    stat'ed for real."""
    real_stat = os.stat

    def fake(path, *args, **kwargs):
        if real_under is not None and str(path).startswith(real_under):
            return real_stat(path, *args, **kwargs)
        if path not in table:
            raise FileNotFoundError(2, 'No such file or directory', path)
        mode, rdev = table[path]
        return fake_stat_result(mode, rdev)
    patcher = mock.patch.object(os, 'stat', fake)
    patcher.start()
    test.addCleanup(patcher.stop)
    return table


BLOCK = stat.S_IFBLK | 0o660
REGULAR = stat.S_IFREG | 0o644


class SubprocessTestCase(unittest.TestCase):
    """self.sp scripts subprocess, self.log records the module's logging."""

    def setUp(self):
        self.log = FakeLog()
        self.sp = FakeSubprocess(self)
