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
"""HLinuxConfigApt writes an apt.conf proxy line for the host of the apt URL
(urlparse -> urllib.parse) and a sources.list.  The generated files are real
temp-dir I/O (their content is the subject); sudo rm is mocked."""
import os
import shutil
import tempfile
import unittest

from tests import csmake_alias
csmake_alias.install()

from tests.helpers import SubprocessTestCase, new_module

hlinuxSkipReason = ''
try:
    # HLinuxConfigApt builds on ShellEnv, which lives in csmake core
    from CsmakeModules.HLinuxConfigApt import HLinuxConfigApt
except ImportError as importFailure:
    # Only a missing csmake core module is a reason to skip; any other
    # import problem in HLinuxConfigApt itself should fail loudly.
    if not (importFailure.name or '').startswith(
            ('CsmakeModules.ShellEnv', 'CsmakeCore')):
        raise
    HLinuxConfigApt = None
    hlinuxSkipReason = "csmake core's ShellEnv is not importable: %s" % importFailure


@unittest.skipIf(HLinuxConfigApt is None, hlinuxSkipReason)
class TestHLinuxConfigApt(SubprocessTestCase):

    def setUp(self):
        SubprocessTestCase.setUp(self)
        self.config = tempfile.mkdtemp(prefix='aptconf')
        self.addCleanup(shutil.rmtree, self.config, True)
        self.module = new_module(HLinuxConfigApt, log=self.log)

    def options(self, **extra):
        options = {'config': self.config,
                   'aptURL': 'http://apt.example.com:3142/mirror',
                   'archive': '2014/repo.1', 'release': 'cattleprod',
                   'sections': 'main contrib',
                   'debootstrap': '/usr/sbin/debootstrap'}
        options.update(extra)
        for key in [k for k, v in options.items() if v is None]:
            del options[key]
        return options

    def read(self, name):
        with open(os.path.join(self.config, 'apt', name)) as handle:
            return handle.read()

    def test_default_proxy_line_uses_the_host_and_port_of_the_url(self):
        self.module.default(self.options())
        self.assertEqual(self.read('apt.conf'),
                         'Acquire::http::Proxy::apt.example.com:3142 DIRECT;\n')

    def test_default_sources_list_points_at_the_archive(self):
        self.module.default(self.options())
        self.assertEqual(
            self.read('sources.list'),
            'deb http://apt.example.com:3142/mirror/hLinuxArchive/2014/repo.1 '
            'cattleprod main contrib\n')

    def test_default_returns_the_dib_environment(self):
        result = self.module.default(self.options())
        apt = os.path.join(self.config, 'apt')
        self.assertEqual(result['DIB_APT_CONF'], os.path.join(apt, 'apt.conf'))
        self.assertEqual(result['DIB_APT_SOURCES'], os.path.join(apt, 'sources.list'))
        self.assertEqual(result['DIB_DISTRIBUTION_MIRROR'],
                         'http://apt.example.com:3142/mirror/hLinuxArchive/2014/repo.1')
        self.assertEqual(result['DIB_RELEASE'], 'cattleprod')
        self.assertEqual(result['DIB_DEBIAN_DEBOOTSTRAP_SCRIPT'], '/usr/sbin/debootstrap')
        self.assertEqual(self.log.results, ['passed'])

    def test_default_repo_overrides_archive_with_a_warning(self):
        result = self.module.default(self.options(repo='hLinux/latest'))
        self.assertEqual(result['DIB_DISTRIBUTION_MIRROR'],
                         'http://apt.example.com:3142/mirror/hLinux/latest')
        self.assertIn('archive and repo options were defined',
                      self.log.messages('warning')[0])

    def test_default_without_archive_or_repo_uses_latest(self):
        result = self.module.default(self.options(archive=None))
        self.assertTrue(result['DIB_DISTRIBUTION_MIRROR'].endswith('/mirror/latest'))
        self.assertIn('An archive or repo was not defined',
                      self.log.messages('info')[0])

    def test_default_does_not_overwrite_existing_files(self):
        os.makedirs(os.path.join(self.config, 'apt'))
        for name in ('apt.conf', 'sources.list'):
            with open(os.path.join(self.config, 'apt', name), 'w') as handle:
                handle.write('keep me\n')
        self.module.default(self.options())
        self.assertEqual(self.read('apt.conf'), 'keep me\n')
        self.assertEqual(self.read('sources.list'), 'keep me\n')

    def test_default_removes_the_previous_apt_directory_with_sudo(self):
        self.module.default(self.options())
        self.assertEqual(self.sp.all_cmds(),
                         [['rm', '-rf', os.path.join(self.config, 'apt')]])
        self.assertTrue(self.sp.calls[0].sudo)

    def test_clean_removes_the_apt_directory_and_returns_the_environment(self):
        result = self.module.clean(self.options())
        self.assertEqual(self.sp.all_cmds(),
                         [['rm', '-rf', os.path.join(self.config, 'apt')]])
        self.assertFalse(os.path.exists(os.path.join(self.config, 'apt')))
        self.assertEqual(result['DIB_OS_ELEMENT'], 'hp-hlinux')
        self.assertEqual(self.log.results, ['passed'])

    def test_clean_phase_variants_delegate_to_clean(self):
        for name in ('clean_build', 'clean_results'):
            with self.subTest(phase=name):
                self.sp.calls.clear()
                getattr(self.module, name)(self.options())
                self.assertEqual(len(self.sp.cmds('rm')), 1)
