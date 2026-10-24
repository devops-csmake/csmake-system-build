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
"""SystemBuildGetPartitionDevices exports the device behind a mountpoint as
an environment variable around the wrapped section."""
from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.SystemBuildGetPartitionDevices import \
    SystemBuildGetPartitionDevices
from tests.helpers import FakeLog, SAMPLE_FILESYSTEM, new_module

import unittest

KEY = '__SystemBuild_demo__'
OPTIONS = {'system': 'demo', 'env_/boot': 'BOOT_DEV', 'env_/': 'ROOT_DEV',
           '**internal': 'ignored'}


class TestGetPartitionDevices(unittest.TestCase):

    def setUp(self):
        self.log = FakeLog()
        self.system = {'filesystem': dict(SAMPLE_FILESYSTEM)}
        self.module = new_module(SystemBuildGetPartitionDevices, log=self.log,
                                 env={KEY: self.system})
        self.env = self.module.env.env

    def test_get_environment_variables_only_returns_env_options(self):
        self.module.options = dict(OPTIONS)
        self.assertEqual(sorted(self.module._getEnvironmentVariables()),
                         [('/', 'ROOT_DEV'), ('/boot', 'BOOT_DEV')])

    def test_start_build_defines_the_device_variables(self):
        self.module.start__build('build', dict(OPTIONS), None, None)
        self.assertEqual(self.env['BOOT_DEV'], '/dev/loop3p2')
        self.assertEqual(self.env['ROOT_DEV'], '/dev/loop3p3')
        self.assertEqual(self.log.results, ['passed'])

    def test_start_build_unknown_mountpoint_gets_a_marker_and_warns(self):
        options = dict(OPTIONS, **{'env_/nope': 'MISSING_DEV'})
        self.module.start__build('build', options, None, None)
        self.assertEqual(self.env['MISSING_DEV'], '## Device not found')
        self.assertEqual(len(self.log.messages('warning')), 1)

    def test_start_build_existing_variable_is_overwritten_with_warning(self):
        self.env['BOOT_DEV'] = 'old'
        self.module.start__build('build', dict(OPTIONS), None, None)
        self.assertEqual(self.env['BOOT_DEV'], '/dev/loop3p2')
        self.assertEqual(len(self.log.messages('warning')), 1)

    def test_start_build_undefined_system_fails(self):
        self.env.pop(KEY)
        self.assertIsNone(self.module.start__build('build', dict(OPTIONS), None, None))
        self.assertEqual(self.log.results, ['failed'])

    def test_start_build_system_without_filesystem_fails(self):
        del self.system['filesystem']
        self.module.start__build('build', dict(OPTIONS), None, None)
        self.assertEqual(self.log.results, ['failed'])
        self.assertNotIn('BOOT_DEV', self.env)

    def test_start_phase_wrappers_delegate_to_start_build(self):
        for name in ('start__system_build', 'start__use_system_build'):
            with self.subTest(joinpoint=name):
                self.env.pop('BOOT_DEV', None)
                getattr(self.module, name)('x', dict(OPTIONS), None, None)
                self.assertEqual(self.env['BOOT_DEV'], '/dev/loop3p2')

    def test_start_other_phase_defines_undefined_markers(self):
        self.module.start('clean', dict(OPTIONS), None, None)
        self.assertEqual(self.env['BOOT_DEV'], '<undefined>')
        self.assertEqual(self.env['ROOT_DEV'], '<undefined>')

    def test_start_build_phase_resolves_devices(self):
        self.module.start('build', dict(OPTIONS), None, None)
        self.assertEqual(self.env['ROOT_DEV'], '/dev/loop3p3')

    def test_end_removes_the_variables(self):
        self.module.start__build('build', dict(OPTIONS), None, None)
        self.module.end__build('build', dict(OPTIONS), None, None)
        self.assertNotIn('BOOT_DEV', self.env)
        self.assertNotIn('ROOT_DEV', self.env)

    def test_end_phase_wrappers_delegate_to_end(self):
        for name in ('end__system_build', 'end__use_system_build'):
            with self.subTest(joinpoint=name):
                self.env['BOOT_DEV'] = 'x'
                getattr(self.module, name)('x', dict(OPTIONS), None, None)
                self.assertNotIn('BOOT_DEV', self.env)

    def test_end_with_variables_never_defined_passes(self):
        self.module.end__build('build', dict(OPTIONS), None, None)
        self.assertEqual(self.log.results, ['passed'])
