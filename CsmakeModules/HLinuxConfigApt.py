# <copyright>
# (c) Copyright 2017 Hewlett Packard Enterprise Development LP
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
from CsmakeModules.ShellEnv import ShellEnv
import os
import os.path
import urllib.parse
import subprocess

class HLinuxConfigApt(ShellEnv):
    """Purpose: Create an apt sources file definition for collecting
             and installing hlinux debs and debootstrap.
             It is encouraged that this module be used within a
                DIBInit env= option
       Library: csmake-system-build
       Phases:
           any - setup the specified apt repo
           clean, clean_build, clean_results - clean the apt files
       Flags:
           config - Directory to place the apt config
               path to apt will be <<config>>/apt
               files created will be apt/apt.conf apt/sources.list
               this w
           aptURL - URL of the apt host
           archive - the hLinux archive to use (2014/repo.2014-11-24.helion.ee.1.1-2, for example)
                archive, repo and aptURL will translate to apt.conf:
                 Acquire::http::Proxy aptURL DIRECT;

                  ---and---
                a sources.list:
                 deb <<aptURL>>/hLinuxArchive/<<archive>> release sections
                 ---or---
                 deb <<aptURL>>/<<repo>> release sections
              NOTE: repo will override archive and if both are defined will
                    produce a warning
           repo - an apt sources for the specified hlinux (will override archive)
           release - release of hlinux to use (cattleprod, for example)
           sections - sections to allow (main contrib non-free, for example)
                     NOTE: This is a space delimited list of sections
           debootstrap - Points to the debootstrap script required
       Returns: A dictionary intended for a shell environment as follows:
           DIB_APT_CONF
           DIB_APT_SOURCES
           DIB_DISTRIBUTION_MIRROR
           DIB_DEBIAN_DEBOOTSTRAP_SCRIPT
           DIB_OS_ELEMENT
           DIB_DEBIAN_DISTRO_NAME
           DIB_BAREMETAL_KERNEL_PATTERN
           DIB_BAREMETAL_INITRD_PATTERN
           USER_DIB_VAR_NODE_DIST
           USER_DIB_VAR_DIB_DISTRIBUTION_MIRROR
           USER_DIB_VAR_DIB_RELEASE
    """

    OPTIONS_REQUIRED = [ 'config', 'aptURL', 'archive', 'repo', 'release', 'sections', 'debootstrap' ]

    #NOTE: The apt repo controls the version of the kernel used
    #      Thus the apt repo needs to be stored in the
    #      build directory results explicitly instead of specified as
    #      an option - since this module is invoked from DIBInit
    #      DIBInit needs to specify the build environment before the
    #      environment options are executed
    #      ALSO - currently DIBInit takes a "release" which should be
    #      driven exclusively by this element (or other similar element)
    #       - it should be the case that Ubuntu or Debian or RHEL, etc
    #         have similar modules that perform similar tasks as this
    #         element does for hLinux

    def clean(self, options):
        self.log.passed()
        return self._cleanApt(options)

    def clean_results(self, options):
        return self.clean(options)

    def clean_build(self, options):
        return self.clean(options)

    def _cleanApt(self, options):
        subprocess.call([
            'sudo', 'rm', '-rf', os.path.join(options['config'],'apt')],
            stdout=self.log.out(),
            stderr=self.log.err() )
        configPath = options['config']
        aptPath= os.path.join(
            configPath,
            'apt' )
        aptURL = options['aptURL']
        aptServer = urllib.parse.urlparse(aptURL)[1]
        release = options['release']
        sections = options['sections']
        debootstrap = options['debootstrap']
        aptRepo = None
        if 'archive' in options:
            aptRepo = "hLinuxArchive/%s" % options['archive']
        if 'repo' in options:
            repoSetting = options['repo']
            if aptRepo is not None:
                self.log.warning("archive and repo options were defined - default will be 'repo' (%s)", repoSetting)
            aptRepo = repoSetting
        if aptRepo is None:
            aptRepo = 'latest'
            self.log.info("An archive or repo was not defined - the build will default to: %s", aptRepo )

        result = {
            "DIB_APT_CONF" : os.path.join(aptPath,'apt.conf' ),
            "DIB_APT_SOURCES" : os.path.join(aptPath,'sources.list' ),
            "DIB_DISTRIBUTION_MIRROR" : "%s/%s" % (aptURL, aptRepo),
            "DIB_RELEASE" : release,
            "DIB_DEBIAN_DEBOOTSTRAP_SCRIPT": debootstrap,
            "DIB_OS_ELEMENT" : 'hp-hlinux',
            "DIB_DEBIAN_DISTRO_NAME" : "hlinux",
            "DIB_BAREMETAL_KERNEL_PATTERN" : "vmlinuz*hlinux",
            "DIB_BAREMETAL_INITRD_PATTERN" : "initrd*hlinux",
            "USER_DIB_VAR_NODE_DIST" : "ubuntu",
            "USER_DIB_VAR_DIB_DISTRIBUTION_MIRROR" : "",
            "USER_DIB_VAR_DIB_RELEASE" : ""
        }
        return result

    def default(self, options):
        self._cleanApt(options)
        configPath = options['config']
        aptPath= os.path.join(
            configPath,
            'apt' )
        aptURL = options['aptURL']
        aptServer = urllib.parse.urlparse(aptURL)[1]
        release = options['release']
        sections = options['sections']
        debootstrap = options['debootstrap']
        aptRepo = None
        if 'archive' in options:
            aptRepo = "hLinuxArchive/%s" % options['archive']
        if 'repo' in options:
            repoSetting = options['repo']
            if aptRepo is not None:
                self.log.warning("archive and repo options were defined - default will be 'repo' (%s)", repoSetting)
            aptRepo = repoSetting
        if aptRepo is None:
            aptRepo = 'latest'
            self.log.info("An archive or repo was not defined - the build will default to: %s", aptRepo )

        if not os.path.exists(aptPath):
            os.makedirs(aptPath)
        aptConfPath = os.path.join(aptPath, 'apt.conf')
        if not os.path.exists(aptConfPath):
            with open(aptConfPath, 'w') as conf:
                conf.write('Acquire::http::Proxy::%s DIRECT;\n' % aptServer)

        sourcesAptPath = os.path.join(aptPath, 'sources.list')
        if not os.path.exists(sourcesAptPath):
            with open(os.path.join(aptPath, 'sources.list'), 'w') as sources:
                sources.write("deb %s/%s %s %s\n" % (
                    aptURL,
                    aptRepo,
                    release,
                    sections ))

        result = {
            "DIB_APT_CONF" : os.path.join(aptPath,'apt.conf' ),
            "DIB_APT_SOURCES" : os.path.join(aptPath,'sources.list' ),
            "DIB_DISTRIBUTION_MIRROR" : "%s/%s" % (aptURL, aptRepo),
            "DIB_RELEASE" : release,
            "DIB_DEBIAN_DEBOOTSTRAP_SCRIPT": debootstrap,
            "DIB_OS_ELEMENT" : 'hp-hlinux',
            "DIB_DEBIAN_DISTRO_NAME" : "hlinux",
            "DIB_BAREMETAL_KERNEL_PATTERN" : "vmlinuz*hlinux",
            "DIB_BAREMETAL_INITRD_PATTERN" : "initrd*hlinux",
            "USER_DIB_VAR_NODE_DIST" : "ubuntu",
            "USER_DIB_VAR_DIB_DISTRIBUTION_MIRROR" : "",
            "USER_DIB_VAR_DIB_RELEASE" : ""
        }
        self.log.passed()
        return result

