# <copyright>
# (c) Copyright 2019 Autumn Samantha Jeremiah Patterson
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
from CsmakeCore.CsmakeAspect import CsmakeModule
import subprocess
import os.path
import fnmatch

class SystemBuildLVM(CsmakeModule):
    """Purpose: Set up LVM on the given system
       Library: csmake-system-build
       Phases: build, system_build - create the definition of the system
               use_system_build - reuse a created lvm system
       Options:
           system - The SystemBuild system name to put LVM on
           pv_<name> - provide the SystemBuildDisk and Partition to use
                       as the physical disk for lvm
           vg_<name> - Takes physical disks and creates a volume group
           lv_<name> - Add a logical volume - format is: <vg>, <size>
       Environment:
           __SystemBuild_<system>__ is referenced - it is an error
               to not have the referenced system defined.
               Logical volumes are added as disks to the system
                 The 'real' field is set to 'False'
                 The 'path' is set to the volume group
                 The 'device' is /dev/<volume group>/<lv>
                 The 'size' is the size of the lv
                 The 'fstab-id' is the device entry used to identify the
                      device in the /etc/fstab
       Requires: lvm2
    """

    REQUIRED_OPTIONS = ['system']

    def _getEnvKey(self, system):
        return "__SystemBuild_%s__" % system

    def _onExit(self):
        #NOTE: The cleanup has to be done very last, after the loop device is
        #      removed from the backing storage, otherwise cleanup will destroy
        #      the disk.
        #NOTE: The LVM configuration also should be available on the actual
        #      installed system.
        self._cleanup(self)

    def _recover(self):
        self._cleanup(True)

    def _cleanup(self, recover=False):
        if len(self.vgsCreated) == 0 and len(self.pvsCreated) == 0:
            return
        self.log.notice("/-----------------------------------\\")
        self.log.notice("| About to wipe LVM information for |")
        self.log.notice("| the build off the build system.   |")
        self.log.notice("|                                   |")
        self.log.notice("| I/O errors expected and OK        |")
        self.log.notice("|                                   |")
        self.log.notice("| 'still mounted' errors are not    |")
        self.log.notice("\\-----------------------------------/")
        vgsremoved = []
        vgsNotRemoved = []
        retry = False
        for vg, pvs in self.vgsCreated:
            result = subprocess.call(
                ['sudo', 'vgchange', '-an', vg],
                stdout=self.log.out(),
                stderr=self.log.err())
        for vg, pvs in self.vgsCreated:
            if vg in vgsremoved:
                continue
            result = subprocess.call(
                ['sudo', 'lvremove', '-f', vg],
                stdout=self.log.out(),
                stderr=self.log.err())
            vgsremoved.append(vg)

        pvsNotRemoved = []
        for pv in self.pvsCreated:
            result = subprocess.call(
                ['sudo', 'pvremove', '-ffy', pv],
                stdout=self.log.out(),
                stderr=self.log.err())
            if result != 0:
                self.log.warning("There was a problem removing physical volume '%s'", pv)
            try:
                subprocess.check_call(
                    ['sudo', 'pvs', pv],
                    stdout=self.log.out(),
                    stderr=self.log.err())
                pvsNotRemoved.append(pv)
                retry = True
            except subprocess.CalledProcessError:
                self.log.debug("PV: %s, confirmed removed", pv)
            except:
                self.log.warning("Could not check to ensure pvs were removed for PV %s", pv)

        for vg, pvs in self.vgsCreated:
            try:
                #We want this to fail!  If it doesn't something is wrong still
                subprocess.check_call(
                    ['sudo', 'lvs', vg],
                    stdout=self.log.out(),
                    stderr=self.log.err())

                #It didn't fail so the vg is still intact
                retry = True
                self.log.warning("The lvs for VG '%s' is still present", vg)
                vgsNotRemoved.append(vg)
            except subprocess.CalledProcessError:
                vgsremoved.append(vg)
                self.log.debug("VG: %s, confirmed lvs were removed", vg)
            except:
                self.log.warning("Could not check to ensure lvs were removed for VG %s", vg)
        #Check to ensure that the lv and pv was really removed.
        if not recover:
            try:
                self.systemEntry['cleanup_methods'].remove(self._cleanup)
            except:
                self.log.debug("No LVM cleanup method found to unregister")

            if retry:
                #We're going to want to requeue this up so it
                #is attempted at the end of the build.
                self.systemEntry['recovery_methods'].append(self._recover)
                return False

        else:
            try:
                self.systemEntry['recovery_methods'].remove(self._recover)
            except:
                self.log.debug("No LVM recovery method found to unregister")

        #Removing all pvs will cause all vg's to go away...
        #Now, clean up any cruft left over in /etc/lvm
        # - umm...I can't even sudo ls /etc/lvm/archive/*, so this is the
        #         next best thing.
        vgsplat = subprocess.check_output(
            ['sudo', 'ls', '-R', '/etc/lvm/archive'],
            stderr=self.log.err() )
        vgfiles = vgsplat.decode('utf-8').split()[1:]
        for vg, pvs in self.vgsCreated:
            for vgfile in vgfiles:
                if fnmatch.fnmatch(vgfile, '%s_*.vg' % vg):
                    result = subprocess.call(
                        ['sudo', 'rm', '-rf',
                            os.path.join("/etc/lvm/archive",vgfile)],
                        stdout = self.log.out(),
                        stderr = self.log.err())
                    if result != 0:
                        self.log.warning("Failed to remove archive file: %s", vgfile)

            result = subprocess.call(
                ['sudo', 'rm', '-rf', '/etc/lvm/backup/%s' % vg ],
                stdout = self.log.out(),
                stderr = self.log.err())
            if result != 0:
                self.log.warning("Failed to remove backup file: %s", '/etc/lvm/backup/%s' % vg)

        self.vgsCreated = []
        self.pvsCreated = []
        self.lvsCreated = []
        try:
            self.systemEntry['cleanup_methods'].remove(self._cleanup)
        except:
            self.log.info("No LVM cleanup method found to unregister")

    def system_build(self, options):
        return self.build(options)
    def build(self, options):
        return self._setupLvm(options, True)

    def use_system_build(self, options):
        return self._setupLvm(options, False)

    def _setupLvm(self, options, build):
        system = options['system']
        key = self._getEnvKey(system)

        if key not in self.env.env:
            self.log.error("System '%s' is not defined", system)
            self.log.failed()
            return None
        systemEntry = self.env.env[key]
        self.systemEntry = systemEntry
        if 'disks' not in systemEntry:
            self.log.error("System '%s' has no disks", system)
            self.log.failed()
            return None

        success = False
        self.pvsCreated = []
        self.vgsCreated = []
        self.lvsCreated = []
        try:
            #Set up all vgs
            vglist = []
            vgpvlists = {}
            currentvgs = []
            currentvgout = subprocess.check_output(
                ['sudo', 'vgs', '--noheadings'],
                stderr=self.log.err() )
            lines = currentvgout.decode('utf-8').split('\n')
            for line in lines:
                if len(line.strip()) == 0:
                    continue
                vgparts = line.split(' ')
                for vgpart in vgparts:
                    current = vgpart.strip()
                    if len(current) > 0:
                        currentvgs.append(current)
                        break
            self.log.devdebug("currentvgs: ", str(currentvgs))

            for option, value in options.items():
                if option.startswith("vg_"):
                    volg = option[3:].strip()
                    if volg in currentvgs:
                        #TODO: Find a way to get the volume groups separated
                        self.log.error("Volume group '%s' already exists on the build system", volg)
                        self.log.failed()
                        return None
                    vglist.append(volg)
                    vgpvlists[volg]=value

            #Set up all pvs
            pvlist = {}
            for option, value in options.items():
                if option.startswith('pv_'):
                    phyv = option[3:]
                    phydev = None
                    disk = None
                    part = None
                    if '.' in value:
                        disk, part = value.split('.', 1)
                    else:
                        disk = value
                    if disk not in systemEntry['disks']:
                        self.log.error("Disk '%s' is not defined", disk)
                        self.log.failed()
                        return None
                    diskEntry = systemEntry['disks'][disk]
                    phydev = diskEntry['device']
                    if part is not None:
                        partEntry = diskEntry['partitions']
                        if part not in partEntry:
                            self.log.error("Partition '%s' in disk '%s' is not defined", part, disk)
                            self.log.failed()
                            return None
                        phydev = "%sp%d" % (
                            phydev,
                            partEntry[part]['number'] )
                    if build:
                        subprocess.check_call(
                            ['sudo', 'pvcreate', '-M2', '-f', '-y', phydev],
                            stdout = self.log.out(),
                            stderr = self.log.err())
                    else:
                        subprocess.check_call(
                            ['sudo', 'pvscan', '--cache', phydev],
                            stdout = self.log.out(),
                            stderr = self.log.err())
                    pvlist[phyv] = phydev
                    self.pvsCreated.append(phydev)

            #This is the rest of the vg processing
            for volg in vglist:
                value = vgpvlists[volg]
                phyvs = value.split(',')
                phydevs = []
                for phyv in phyvs:
                    current = phyv.strip()
                    if current not in pvlist:
                        self.log.error("pv '%s' not created", current)
                        self.log.failed()
                        return None
                    phydev = pvlist[current]
                    phydevs.append(phydev)
                if build:
                    calllist = ['sudo', 'vgcreate', '-M2', volg]
                    calllist.extend(phydevs)
                    subprocess.check_call(
                        calllist,
                        stdout = self.log.out(),
                        stderr = self.log.err() )
                else:
                    subprocess.check_call(
                        ['sudo', 'vgchange', '-ay', volg],
                        stdout = self.log.out(),
                        stderr = self.log.err() )
                self.vgsCreated.append((volg, phydevs))

            results = {}
            for option, value in options.items():
                if option.startswith("lv_"):
                    logv = option[3:]
                    volg, size = value.split(',',1)
                    volg = volg.strip()
                    size = size.strip()
                    if volg not in vglist:
                        self.log.error("Logical Volume '%s' error: Volume group '%s' not defined", logv, volg)
                        self.log.failed()
                        return None
                    if build:
                        subprocess.check_call(
                            ['sudo', 'lvcreate', '-n', logv, '-L', size, volg],
                            stdout = self.log.out(),
                            stderr = self.log.err())
                    else:
                        subprocess.check_call(
                            ['sudo', 'lvchange', '-ay', "{}/{}".format(volg, logv)],
                            stdout = self.log.out(),
                            stderr = self.log.err())
                    self.lvsCreated.append((logv, volg))

                    #Add to the "disks" available. assume dsf == dev/volg/logv
                    bytesize = systemEntry['system']._getSizeInBytes(size)
                    if logv in systemEntry['disks']:
                        self.log.error("Logical volume '%s' error: Name must be unique from other logical volumes and system disks")
                        self.log.failed()
                        return None
                    systemEntry['disks'][logv] = {
                        'device' : '/dev/%s/%s' % (volg, logv),
                        'fstab-id' : '/dev/mapper/%s-%s' % (
                            volg.replace('-', '--'),
                            logv.replace('-', '--') ),
                        'real' : False,
                        'size' : bytesize,
                        'path' : volg }
                    results[logv] = systemEntry['disks'][logv]
            success = True
            verbose_params = []
            if self.settings['verbose']:
                verbose_params = ['-v']
            if self.settings['debug']:
                verbose_params = ['-vv']
            subprocess.call(
                ['sudo', 'vgmknodes'] + verbose_params,
                stdout = self.log.out(),
                stderr = self.log.err())

            #Cleanup methods are executed in reverse order
            #The lvm cleanup has to occur after the loop device cleanup,
            #or wreck the lvms created on the device.
            #So, this cleanup has to go last.
            systemEntry['cleanup_methods'].insert(0,self._cleanup)
        finally:
            if not success:
                self._cleanup()
        self.log.passed()
        return results
