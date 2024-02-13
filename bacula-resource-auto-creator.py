#!/usr/bin/python3
# ----------------------------------------------------------------------------
# - bacula-resource-auto-creator.py
# ----------------------------------------------------------------------------

# waa - 20240131 - Initial re-write of my `checkDriveIndexes.sh` script from
#                  bash into Python.
#                - The final goal will be to use this initial process of
#                  identifying libraries, and drives, and then tying the
#                  drives to Bacula SD `DriveIndex` settings as a base to
#                  generate cut-n-paste Bacula resource configurations for
#                  the Director Storage, the SD Autochanger it points to
#                  and the Drive Devices in the Autochanger.
#
# The latest version of this script may be found at: https://github.com/waa
#
# ----------------------------------------------------------------------------
#
# BSD 2-Clause License
#
# Copyright (c) 2024, William A. Arlofski waa@revpol.com
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1.  Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#
# 2.  Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
# TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# ----------------------------------------------------------------------------
#
# Import the required modules
# ---------------------------
import os
import re
import sys
import subprocess
from time import sleep
from random import randint
from datetime import datetime

# Set some variables
# ------------------
progname = 'Bacula Resource Auto Creator'
version = '0.09'
reldate = 'February 13, 2024'
progauthor = 'Bill Arlofski'
authoremail = 'waa@revpol.com'
scriptname = 'bacula-resource-auto-creator.py'
prog_info_txt = progname + ' - v' + version + ' - ' + scriptname \
              + '\nBy: ' + progauthor + ' ' + authoremail + ' (c) ' + reldate + '\n'

# Should all debugging information be logged?
# (ie: mtx, mt outputs, and reporting of all actions)
# ---------------------------------------------------
debug = False

# How long to sleep between mt and mtx
# commands. This should typically not be zero
# -------------------------------------------
sleep_secs = 10

# Do the tape drive(s) require that we issue
# the mt offline before unloading a drive?
# ------------------------------------------
offline = False

# list of tape libraries to skip during testing
# ---------------------------------------------
# If testing with mhVTL, skip the scsi-SSTK_L700_XYZZY_A library because it has LTO8/9
# tapes and LTO8/9 drives. An error is thrown if an LTOx tape is loaded into LTOy drive
# -------------------------------------------------------------------------------------
libs_to_skip = ['scsi-SSTK_L700_XYZZY_A', 'otherLibToSkip']

# ==================================================
# Nothing below this line should need to be modified
# ==================================================

# Now for some functions
# ----------------------
def now():
    'Return the current date/time in human readable format.'
    return datetime.today().strftime('%Y%m%d%H%M%S')

def usage():
    'Show the instructions and script information.'
    # print(doc_opt_str)
    print(prog_info_txt)
    sys.exit(1)

def log(text):
    'Given some text, print it to stdout and write it to the log file.'
    print(text)
    with open(log_file, 'a+') as file:
        file.write(text + '\n')

def log_cmd_results(result):
    'Given a subprocess.run() result object, clean up the extra line feeds from stdout and stderr and log them.'
    stdout = result.stdout.rstrip('\n')
    stderr = result.stderr.rstrip('\n')
    if stdout == '':
        stdout = 'N/A'
    if stderr == '':
        stderr = 'N/A'
    log('returncode: ' + str(result.returncode))
    log('stdout: ' + ('\n[begin stdout]\n' + stdout + '\n[end stdout]' if '\n' in stdout else stdout))
    log('stderr: ' + ('\n[begin stderr]\n' + stderr + '\n[end stderr]' if '\n' in stderr else stderr))

def chk_cmd_result(result, cmd):
    'Given a result object, check the returncode, then log and exit if non zero.'
    if result.returncode != 0:
        log('ERROR calling: ' + cmd)
        log('Exiting with errorlevel ' + str(result.returncode))
        sys.exit(result.returncode)

def get_shell_result(cmd):
    'Given a command to run, return the subprocess.run() result.'
    return subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

def get_uname():
    'Get the OS uname to be use in other tests.'
    log('- Getting OS\'s uname for use in other tests')
    cmd = 'uname'
    if debug:
        log('shell command: ' + cmd)
    result = get_shell_result(cmd)
    if debug:
        log_cmd_results(result)
    chk_cmd_result(result, cmd)
    return result.stdout.rstrip('\n')

def get_ready_str():
    'Determine the OS to set the correct mt "ready" string.'
    log('- Determining the correct mt "ready" string')
    if uname == 'Linux':
        if os.path.isfile('/etc/debian_version'):
            cmd = 'mt --version | grep "mt-st"'
            if debug:
                log('mt command: ' + cmd)
            result = get_shell_result(cmd)
            if debug:
                log_cmd_results(result)
            if result.returncode == 1:
                return 'drive status'
        else:
            cmd = 'mt --version | grep "GNU cpio"'
            if debug:
                log('mt command: ' + cmd)
            result = get_shell_result(cmd)
            if debug:
                log_cmd_results(result)
            if result.returncode == 0:
                return 'drive status'
        return 'ONLINE'
    elif uname == 'SunOS':
        return 'No Additional Sense'
    elif uname == 'FreeBSD':
        return 'Current Driver State: at rest.'
    elif uname == 'OpenBSD':
        return 'ds=3<Mounted>'
    else:
        print(print_opt_errors('uname'))
        usage()

def lib_or_drv_status(cmd):
    if debug:
        log('Command: ' + cmd)
    result = get_shell_result(cmd)
    if debug:
        log_cmd_results(result)
    chk_cmd_result(result, cmd)
    return result

def loaded(lib, index):
    'If the drive (index) is loaded, return the slot and volume that is in it, otherwise return 0, 0'
    result = lib_or_drv_status('mtx -f /dev/tape/by-id/' + lib + ' status')
    drive_loaded_line = re.search('Data Transfer Element ' + str(index) + ':Full.*', result.stdout)
    if drive_loaded_line is not None:
        slot_and_vol_loaded = (re.sub('^Data Transfer Element.*Element (\d+) Loaded.*= (\w+)', '\\1 \\2', drive_loaded_line.group(0))).split()
        slot_loaded = slot_and_vol_loaded[0]
        vol_loaded = slot_and_vol_loaded[1]
        log(' - Drive ' \
            + str(index) + ' is loaded with volume ' + vol_loaded + ' from slot ' + slot_loaded)
        if debug:
            log('loaded output: ' + slot_loaded)
        return slot_loaded, vol_loaded
    else:
        log(' - Drive ' + str(index) + ' is empty')
        return '0', '0'

def get_random_slot(lib):
    'Return a pseudo-random slot that contains a tape and the volume name in the slot.'
    result = lib_or_drv_status('mtx -f /dev/tape/by-id/' + lib + ' status | grep "Storage Element [0-9]\{1,3\}:Full" | grep -v "CLN"')
    full_slots_lst = re.findall('Storage Element [0-9].?:Full.* ', result.stdout)
    rand_int = randint(0, len(full_slots_lst) - 1)
    slot = re.sub('Storage Element ([0-9].?):Full.*', '\\1', full_slots_lst[rand_int])
    vol = re.sub('.*:VolumeTag=(.*).*', '\\1', full_slots_lst[rand_int]).rstrip()
    return slot, vol

def unload(lib, slot, drive):
    cmd = 'mtx -f /dev/tape/by-id/' + lib + ' unload ' + slot + ' ' + str(drive)
    if debug:
        log('mtx command: ' + cmd)
    result = get_shell_result(cmd)
    if result.returncode == 0:
        log('    - Unload successful')
    else:
        log('    - Unload failed')
    if debug:
        log_cmd_results(result)
    chk_cmd_result(result, cmd)
    return

def write_res_file(filename, text):
    'Given a filename and some text, write the text to the file.'
    with open(filename, 'a+') as file:
        file.write(text)

# ================
# BEGIN THE SCRIPT
# ================

# Set the log directory and file name. This directory will also
# be where we write the cut-n-paste Bacula resource configurations
# ----------------------------------------------------------------
date_stamp = now()
lower_name_and_time = progname.replace(' ', '-').lower() + '_' + date_stamp
work_dir = '/tmp/' + lower_name_and_time
log_file = work_dir + '/' + lower_name_and_time + '.log'

# Create the lib_dict dictionary. It will hold {'libraryName': ('drive_byid_node', drive_index)...}
# -------------------------------------------------------------------------------------------------
lib_dict = {}

# Create the work_dir directory
# -----------------------------
os.mkdir(work_dir)

# Create the string added to Resource config files 'Description =' line
# ---------------------------------------------------------------------
created_by_str = 'Created by ' + progname + ' v' + version + ' - ' + date_stamp

# Set up the text string templates for the three types of
# resource configuration files that need to be created
# -------------------------------------------------------
director_storage_tpl = """Storage {
  Name =
  Description =
  Address =
  Password =
  Autochanger =
  Device =
  MaximumConcurrentJobs =
  MediaType =
  SdPort = 9103
}"""

storage_autochanger_tpl = """Autochanger {
  Name =
  Description =
  ChangerCommand = "/opt/bacula/scripts/mtx-changer %c %o %S %a %d"
  ChangerDevice =
  Device =
}"""

storage_device_tpl = """Device {
  Name =
  Description =
  DriveIndex =
  DeviceType = Tape
  MediaType =
  Autochanger = yes
  AlwaysOpen = yes
  AutomaticMount = yes
  LabelMedia = no
  RandomAccess = no
  RemovableMedia = yes
  MaximumConcurrentJobs = 1
  ArchiveDevice =
}"""

# Log the startup header
# ----------------------
hdr = '[ Starting ' + sys.argv[0] + ' v' + version + ' ]'
log('\n\n' + '='*10 + hdr + '='*10)
log('- Work directory: ' + work_dir)
log('- Logging to file: ' + lower_name_and_time + '.log')

# Get the OS's uname to be used in other tests
# --------------------------------------------
uname = get_uname()

# Check the OS to assign the 'ready' variable
# to know when a drive is loaded and ready.
# -------------------------------------------
ready = get_ready_str()

# First, we get the list of tape libraries' sg nodes
# --------------------------------------------------
log('- Getting the list of tape libraries\' sg nodes')
cmd = 'lsscsi -g | grep mediumx | grep -o "sg[0-9]*" | sort'
if debug:
    log('lsscsi command: ' + cmd)
result = get_shell_result(cmd)
if debug:
    log_cmd_results(result)
chk_cmd_result(result, cmd)
libs_sg_lst = result.stdout.rstrip('\n').split('\n')
num_libs = len(libs_sg_lst)
log(' - Found ' + str(num_libs) + ' librar' + ('ies' if num_libs == 0 or num_libs > 1 else 'y'))
log('  - Library sg node' + ('s' if num_libs > 1 else '') + ': ' + str(', '.join(libs_sg_lst)))

# waa - 20240203 - Need to see the /dev/tape/by-id directory and compare to lsscsi output
# ---------------------------------------------------------------------------------------
if debug:
    log('Command \'lsscsi -g\' output:')
cmd = 'lsscsi -g'
result = get_shell_result(cmd)
if debug:
    log_cmd_results(result)
chk_cmd_result(result, cmd)

if debug:
    log('Command \'ls -la /dev/tape/by-id\' output:')
cmd = 'ls -la /dev/tape/by-id'
result = get_shell_result(cmd)
if debug:
    log_cmd_results(result)
chk_cmd_result(result, cmd)
dev_tape_by_id_txt = result.stdout.rstrip('\n')

# From the libraries' sg nodes, get the corresponding by-id node
# --------------------------------------------------------------
if num_libs != 0:
    libs_byid_nodes_lst = []
    log('- Determining libraries\' by-id nodes from their sg nodes')
    for lib_sg in libs_sg_lst:
        libs_byid_nodes_lst.append(re.sub('.* (scsi-.+?) ->.*/' + lib_sg + '.*', '\\1', dev_tape_by_id_txt, flags = re.DOTALL))
    log(' - Library by-id node' + ('s' if num_libs > 1 else '') + ': ' + str(', '.join(libs_byid_nodes_lst)))

# Get a list of tape drives' st nodes
# -----------------------------------
log('- Getting the list of tape drives\' st nodes')
cmd = 'lsscsi -g | grep tape | grep -o "st[0-9]*" | sort'
if debug:
    log('lsscsi command: ' + cmd)
result = get_shell_result(cmd)
if debug:
    log_cmd_results(result)
chk_cmd_result(result, cmd)
drives_st_lst = result.stdout.rstrip('\n').split('\n')
num_drives = len(drives_st_lst)
log(' - Found ' + str(num_drives) + ' drive' + ('s' if num_drives == 0 or num_drives > 1 else ''))
log('  - Tape drive st node' + ('s' if num_drives > 1 else '') + ': ' + str(', '.join(drives_st_lst)))

# From the drives' st nodes, get the corresponding by-id 'nst' node
# -----------------------------------------------------------------
if num_drives != 0:
    drives_byid_nodes_lst = []
    log('- Determining drives\' by-id nodes from their st nodes')
    for drive_st in drives_st_lst:
        drives_byid_nodes_lst.append(re.sub('.* (scsi-.+?) ->.*/n' + drive_st + '\n.*', '\\1', dev_tape_by_id_txt, flags = re.DOTALL))
    log(' - Tape drive by-id node' + ('s' if num_drives > 1 else '') + ': ' + str(', '.join(drives_byid_nodes_lst)))
hdr = '[ Startup Complete ]'
log('='*10 + hdr + '='*10)

# If 'offline' is True send the offline command to all drives first
# -----------------------------------------------------------------
hdr = '\nChecking if we send \'offline\' command to all drives in the Librar' + ('ies' if num_libs > 1 else 'y') + ' Found\n'
log('\n\n' + '='*(len(hdr) - 2) + hdr + '='*(len(hdr) - 2))
if offline:
    # First send each drive the offline command
    # -----------------------------------------
    log('- The \'offline\' variable is True, sending all drives offline command')
    for drive_byid in drives_byid_nodes_lst:
        log(' - Drive /dev/tape/by-id/' + drive_byid)
        cmd = 'mt -f /dev/tape/by-id/' + drive_byid + ' offline'
        if debug:
            log('mt command: ' + cmd)
        result = get_shell_result(cmd)
        if debug:
            log_cmd_results(result)
        chk_cmd_result(result, cmd)
else:
    log('- The \'offline\' variable is False, skip sending offline commands')

# For each library found, unload each of the drives in it before
# starting the process of identifying the Bacula DriveIndexes
# --------------------------------------------------------------
hdr = '\nUnloading All Tape Drives In The (' + str(num_libs) + ') Librar' + ('ies' if num_libs > 1 else 'y') + ' Found\n'
log('\n\n' + '='*(len(hdr) - 2) + hdr + '='*(len(hdr) - 2))
for lib in libs_byid_nodes_lst:
    result = lib_or_drv_status('mtx -f /dev/tape/by-id/' + lib + ' status')
    num_drives = len(re.findall('Data Transfer Element', result.stdout, flags = re.DOTALL))
    hdr = '\n' + lib + ': Unloading (' + str(num_drives) + ') Tape Drives\n'
    log('-'*(len(hdr) - 2) + hdr + '-'*(len(hdr) - 2))
    # Unload all the drives in the library
    # ------------------------------------
    drive_index = 0
    while drive_index < num_drives:
        log('- Checking if a tape is in drive ' + str(drive_index))
        slot_loaded, vol_loaded = loaded(lib, drive_index)
        if slot_loaded != '0':
            log('  - Unloading volume ' + vol_loaded + ' from drive ' + str(drive_index) + ' to slot ' + slot_loaded)
            unload(lib, slot_loaded, drive_index)
        drive_index += 1
    log('')

# Now, iterate through each Library found, get the number of drives
# in it, then load a tape into each one, and attempt to identify
# the by-id node having a tape in it, and correlate its drive index
# -----------------------------------------------------------------
hdr = '\nIterating Through Each Library Found\n'
log('\n' + '='*(len(hdr) - 2) + hdr + '='*(len(hdr) - 2))
for lib in libs_byid_nodes_lst:
    result = lib_or_drv_status('mtx -f /dev/tape/by-id/' + lib + ' status')
    num_drives = len(re.findall('Data Transfer Element', result.stdout, flags = re.DOTALL))
    hdr = '\nLibrary \'' + lib + '\' with (' + str(num_drives) + ') drives\n'
    log('-'*(len(hdr) - 2) + hdr + '-'*(len(hdr) - 2))
    # Now iterate through each drive, load a tape in it
    # and then check to see which drive by-id is loaded
    # -------------------------------------------------
    if lib in libs_to_skip:
        log('- Skipping library: ' + lib + '\n')
        continue
    else:
        drive_index = 0
        while drive_index < num_drives:
            hdr = '\nIdentifying DriveIndex ' + str(drive_index) + '\n'
            log('-'*(len(hdr) - 2) + hdr + '-'*(len(hdr) - 2))
            slot, vol  = get_random_slot(lib)
            log('- Loading volume ' + vol + ' from slot ' + slot + ' into drive ' + str(drive_index))
            cmd = 'mtx -f /dev/tape/by-id/' + lib + ' load ' + slot + ' ' + str(drive_index)
            if debug:
                log('mtx command: ' + cmd)
            result = get_shell_result(cmd)
            if result.returncode == 0:
                log(' - Loaded OK')
            else:
                log(' - Load FAILED')
            if debug:
                log_cmd_results(result)
            chk_cmd_result(result, cmd)
            log('  - Sleeping ' + str(sleep_secs) + ' seconds to allow drive to settle')
            sleep(sleep_secs)

            # Test by-id device nodes with mt to identify drive's index
            # ---------------------------------------------------------
            for drive_byid_node in drives_byid_nodes_lst:
                if debug:
                    log('- Checking drive by-id node \'/dev/tape/by-id/' + drive_byid_node + '\'')
                result = lib_or_drv_status('mt -f /dev/tape/by-id/' + drive_byid_node + ' status')
                if re.search(ready, result.stdout, re.DOTALL):
                    log(' - ' + ready + ': Tape ' + vol + ' is loaded in /dev/tape/by-id/' + drive_byid_node)
                    log('  - This is Bacula \'DriveIndex = ' + str(drive_index) + '\'')
                    # We found the drive with the tape loaded in it so
                    # add the current lib, by-id node, drive_index to the
                    # lib_dict dictionary, and remove the by-id node from
                    # the drive_byid_nodes_lst list
                    # ---------------------------------------------------
                    if lib in lib_dict:
                        lib_dict[lib].append((drive_byid_node, drive_index))
                    else:
                        lib_dict[lib] = [(drive_byid_node, drive_index)]
                    drives_byid_nodes_lst.remove(drive_byid_node)
                    # Now unload the drive
                    # --------------------
                    log('   - Unloading drive ' + str(drive_index))
                    unload(lib, slot, drive_index)
                    break
                else:
                    if debug:
                        log(' - EMPTY: Drive by-id node \'' + drive_byid_node + '\' is empty')
            drive_index += 1
        log('')
hdr = '[ Bacula Drive \'ArchiveDevice\' => Bacula \'DriveIndex\' settings ]'
log('\n' + '='*8 + hdr + '='*8) 
for lib in libs_byid_nodes_lst:
    hdr = '\nLibrary: ' + lib + '\n'
    log('-'*(len(hdr) - 2) + hdr + '-'*(len(hdr) - 2))
    if lib not in lib_dict:
        log('No drives were detected in this library, or it was intentionally skipped')
    else:
        for drive_index_tuple in lib_dict[lib]:
            log('ArchiveDevice = /dev/tape/by-id/' + drive_index_tuple[0] + ' => DriveIndex = ' + str(drive_index_tuple[1]))
    log('')
if len(drives_byid_nodes_lst) != 0:
    drives_byid_nodes_lst.sort()
    hdr = '\nStand Alone Drive' + ('s' if len(drives_byid_nodes_lst) > 1 else '') + ' (May be in a library that was skipped)\n'
    log('-'*(len(hdr) - 2) + hdr + '-'*(len(hdr) - 2))
    log(', '.join(drives_byid_nodes_lst))
log('='*80)

# Generate the Bacula resource cut-n-paste configurations
# -------------------------------------------------------
hdr = '\nGenerating Bacula Resource Configuration Files For Each Library Found With Drives\n'
log('\n\n' + '='*(len(hdr) - 2) + hdr + '='*(len(hdr) - 2))
for lib in lib_dict:
    hdr = '\nLibrary: ' + lib + '\n'
    log('-'*(len(hdr) - 2) + hdr + '-'*(len(hdr) - 2))
    log('- Generating Director Storage Resource')
    autochanger_name = 'Autochanger_' + lib.replace('scsi-', '')

    # Director Storage
    # ----------------
    res_file = work_dir + '/DirectorStorage_' + autochanger_name + '.cfg'
    res_txt = director_storage_tpl
    res_txt = res_txt.replace('Name =', 'Name = "' + autochanger_name + '"')
    res_txt = res_txt.replace('Description =', 'Description = "Autochanger with (' \
            + str(len(lib_dict[lib])) + ') drives - ' + created_by_str + '"')
    res_txt = res_txt.replace('Address =', 'Address = "127.0.0.1"       # You *must* replace this with the correct FQDN!')
    res_txt = res_txt.replace('Password =', 'Password = "wrongPassword"  # You *must* replace this with the correct password for the SD @ Address')
    res_txt = res_txt.replace('Autochanger =', 'Autochanger = "' + autochanger_name + '"')
    res_txt = res_txt.replace('Device =', 'Device = "' + autochanger_name + '"')
    res_txt = res_txt.replace('MaximumConcurrentJobs =', 'MaximumConcurrentJobs = ' + str(len(lib_dict[lib])))
    res_txt = res_txt.replace('MediaType =', 'MediaType = "' + lib.replace('scsi-', '') + '"')
    # Open and write Director Storage resource config file
    # ----------------------------------------------------
    write_res_file(res_file, res_txt)
    log(' - Done')

    # Storage Autochanger
    # -------------------
    log('- Generating Storage Autochanger And Device Resources')
    res_file = work_dir + '/StorageAutochanger_' + autochanger_name + '.cfg'
    res_txt = storage_autochanger_tpl
    res_txt = res_txt.replace('Name =', 'Name = "' + autochanger_name + '"')
    res_txt = res_txt.replace('Description =', 'Description = "' + created_by_str + '"')
    res_txt = res_txt.replace('ChangerDevice =', 'ChangerDevice = "/dev/tape/by-id/' + lib + '"')
    dev_str = ' Device = '
    dev = 0
    autochanger_dev_str = ''
    while dev < len(lib_dict[lib]):
        log(' - Generating Device Resource: ' + autochanger_name + '_Dev' + str(dev))
        autochanger_dev_str += '"' + autochanger_name + '_Dev' + str(dev) + '"' + (', ' if dev <= (len(lib_dict[lib]) - 2) else '')
        # Create matching Storage Device resource config for each drive device
        # --------------------------------------------------------------------
        drv_res_file = work_dir + '/StorageDevice_' + autochanger_name + '_Dev' + str(dev) + '.cfg'
        drv_res_txt = storage_device_tpl
        drv_res_txt = drv_res_txt.replace('Name =', 'Name = "' + autochanger_name + '_Dev' + str(dev) + '"')
        drv_res_txt = drv_res_txt.replace('Description =', 'Description = "Drive ' + str(dev) \
                    + ' in ' + autochanger_name + ' - ' +created_by_str + '"')
        drv_res_txt = drv_res_txt.replace('DriveIndex =', 'DriveIndex = ' + str(dev))
        drv_res_txt = drv_res_txt.replace('MediaType =', 'MediaType = "' + lib.replace('scsi-', '') + '"')
        for drive_index_tuple in lib_dict[lib]:
            if drive_index_tuple[1] == dev:
                archive_device = drive_index_tuple[0]
                continue
        drv_res_txt = drv_res_txt.replace('ArchiveDevice =', 'ArchiveDevice = "/dev/tape/by-id/' + archive_device + '"')
        # Open and write Storage Device resource config file
        # --------------------------------------------------
        write_res_file(drv_res_file, drv_res_txt)
        dev += 1
        log('  - Done')
    res_txt = res_txt.replace(' Device =', ' Device = ' + autochanger_dev_str)
    # Open and write Storage Autochanger config file
    # ----------------------------------------------
    write_res_file(res_file, res_txt)
    log(' - Storage Autochanger And Drive Device Resources Done\n')

# Print location of log file and resource config files
# ----------------------------------------------------
log('\n' + '='*107)
log('DONE: Script output log file and Bacula resource configuration files in: ' + work_dir)
log('NOTE: Before use, you *MUST* edit the following Director Storage resource file' + ('s' if len(lib_dict) > 1 else '') + ' in the directory above:')
for lib in lib_dict:
    autochanger_name = 'Autochanger_' + lib.replace('scsi-', '')
    log('      * DirectorStorage_' + autochanger_name + '.cfg')
log('='*107)
log(prog_info_txt)
