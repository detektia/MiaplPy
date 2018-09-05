#!/usr/bin/env python3
########################
#Author: Heresh Fattahi
#Modified by Sara Mirzaee
#######################

import os, imp, sys, glob, fnmatch
sys.path.insert(0, os.getenv('$PARENTDIR/sources/sentinelStack'))
sys.path.insert(0, os.getenv('$SQUEESAR'))
#sys.path.append('$PARENTDIR/sources/sentinelStack')
#sys.path.append('$SQUEESAR')
import argparse
import configparser
import  datetime
import numpy as np
import isce
import isceobj
from isceobj.Sensor.TOPS.Sentinel1 import Sentinel1
from Stack import config, run, sentinelSLC

helpstr= '''

Stack processor for Sentinel-1 data using ISCE software.

For a full list of different options, try stackSentinel.py -h

stackSentinel.py generates all configuration and run files required to be executed for a stack of Sentinel-1 TOPS data. 

Following are required to start processing:

1) a folder that includes Sentinel-1 SLCs, 
2) a DEM (Digital Elevation Model) 
3) a folder that includes precise orbits (use dloadOrbits.py to download or to update your orbit folder) 
4) a folder for Sentinel-1 Aux files (which is used for correcting the Elevation Antenna Pattern). 
5) bounding box as South North West East. 


Change the --text_cmd option as you wish. 

Note that stackSentinel.py does not process any data. It only prepares a lot of input files for processing and a lot of run files. Then you need to execute all those generated run files in order. To know what is really going on, after running stackSentinel.py, look at each run file generated by stackSentinel.py. Each run file actually has several commands that are independent from each other and can be executed in parallel. The config files for each run file include the processing options to execute a specific command/function.

Note also that run files need to be executed in order, i.e., running run_3 needs results from run_2, etc.

Example:
# slc workflow that produces a coregistered stack of SLCs  

stackSentinel.py -s ../SLC/ -d ../../MexicoCity/demLat_N18_N20_Lon_W100_W097.dem.wgs84 -b '19 20 -99.5 -98.5' -a ../../AuxDir/ -o ../../Orbits -C NESD  -W slc -P squeesar
'''
##############################################

class customArgparseAction(argparse.Action):
    def __call__(self, parser, args, values, option_string=None):
        '''
        The action to be performed.
        '''
        print(helpstr)
        parser.exit()


def createParser():
    parser = argparse.ArgumentParser( description='Preparing the directory structure and config files for stack processing of Sentinel data')

    parser.add_argument('-H','--hh', nargs=0, action=customArgparseAction,
                help='Display detailed help information.')

    parser.add_argument('-s', '--slc_directory', dest='slc_dirname', type=str, required=True,
            help='Directory with all Sentinel SLCs')

    parser.add_argument('-o', '--orbit_directory', dest='orbit_dirname', type=str, required=True,
            help='Directory with all orbits')

    parser.add_argument('-a', '--aux_directory', dest='aux_dirname', type=str, required=True,
            help='Directory with all orbits')
                
    parser.add_argument('-w', '--working_directory', dest='work_dir', type=str, default='./',
            help='Working directory ')
    
    parser.add_argument('-d', '--dem', dest='dem', type=str, required=True,
            help='Directory with slave acquisition')
    
    parser.add_argument('-m', '--master_date', dest='master_date', type=str, default=None,
            help='Directory with slave acquisition')

    parser.add_argument('-c','--num_connections', dest='num_connections', type=str, default = '1',
            help='number of interferograms between each date and subsequent dates')

    parser.add_argument('-O','--num_overlap_connections', dest='num_overlap_connections', type=str, default = '3',
                help='number of overlap interferograms between each date and subsequent dates')

    parser.add_argument('-n', '--swath_num', dest='swath_num', type=str, default='1 2 3',
            help='A list of swaths to be processed')

    parser.add_argument('-b', '--bbox', dest='bbox', type=str, default=None, help='Lat/Lon Bounding SNWE')

    parser.add_argument('-t', '--text_cmd', dest='text_cmd', type=str, default='source ~/.bash_profile;'
       , help='text command to be added to the beginning of each line of the run files. Example : source ~/.bash_profile;')

    parser.add_argument('-x', '--exclude_dates', dest='exclude_dates', type=str, default=None
       , help='List of the dates to be excluded for processing')

    parser.add_argument('-z', '--azimuth_looks', dest='azimuthLooks', type=str, default='3'
       , help='Number of looks in azimuth for interferogram multi-looking')
    
    parser.add_argument('-r', '--range_looks', dest='rangeLooks', type=str, default='9'
       , help='Number of looks in range for interferogram multi-looking')

    parser.add_argument('-f', '--filter_strength', dest='filtStrength', type=str, default='0.5'
       , help='filter strength for interferogram filtering')

    parser.add_argument('-e', '--esd_coherence_threshold', dest='esdCoherenceThreshold', type=str, default='0.85'
           , help='Coherence threshold for estimating azimuth misregistration using enhanced spectral diversity')

    parser.add_argument('--snr_misreg_threshold', dest='snrThreshold', type=str, default='10'
               , help='SNR threshold for estimating range misregistration using cross correlation')

    parser.add_argument('-u', '--unw_method', dest='unwMethod', type=str, default='snaphu'
       , help='unwrapping method (icu or snaphu)')

    parser.add_argument('-p', '--polarization', dest='polarization', type=str, default='vv'
       , help='SAR data polarization')

    parser.add_argument('-C', '--coregistration', dest='coregistration', type=str, default='NESD'
           , help='Coregistration options: a) geometry b) NESD. Default : NESD')

    parser.add_argument('-W', '--workflow', dest='workflow', type=str, default='interferogram'
       , help='The InSAR processing workflow : (interferogram, offset, slc, correlation)')
       
       
    parser.add_argument('-P', '--processingmethod', dest='ProcessingMethod', type=str, default='sbas'
        , help='The InSAR processing method : (sbas, squeesar, ps)')

    return parser
    
    
def cmdLineParse(iargs = None):
    parser = createParser()
    inps = parser.parse_args(args=iargs)
    inps.slc_dirname = os.path.abspath(inps.slc_dirname)
    inps.orbit_dirname = os.path.abspath(inps.orbit_dirname)
    inps.aux_dirname = os.path.abspath(inps.aux_dirname)
    inps.work_dir = os.path.abspath(inps.work_dir)
    inps.dem = os.path.abspath(inps.dem)

    return inps


####################################
def get_dates(inps):
    # Given the SLC directory This function extracts the acquisition dates
    # and prepares a dictionary of sentinel slc files such that keys are 
    # acquisition dates and values are object instances of sentinelSLC class
    # which is defined in Stack.py

    if inps.bbox is not None:
        bbox = [float(val) for val in inps.bbox.split()]

    if inps.exclude_dates is not None:
        excludeList = inps.exclude_dates.split(',')
    else:
        excludeList = []

    if os.path.isfile(inps.slc_dirname):
        print('reading SAFE files from: ' + inps.slc_dirname)
        SAFE_files = []
        for line in open(inps.slc_dirname):
            SAFE_files.append(str.replace(line,'\n','').strip())
    
    else:
        SAFE_files = glob.glob(os.path.join(inps.slc_dirname,'S1*_IW_SLC*')) 

    if len(SAFE_files) == 0:
        raise Exception('No SAFE file found')

    elif len(SAFE_files) == 1:
        raise Exception('At least two SAFE file is required. Only one SAFE file found.')

    else:
        print ("Number of SAFE files found: "+str(len(SAFE_files)))

    ################################
    # write down the list of SAFE files in a txt file:
    f = open('SAFE_files.txt','w') 
    for safe in SAFE_files:
        f.write(safe + '\n') 
    f.close()            
    ################################
  
    safe_dict={}
    for safe in SAFE_files:
        safeObj=sentinelSLC(safe)
        safeObj.get_dates()
        safeObj.get_orbit(inps.orbit_dirname, inps.work_dir)
        if safeObj.date  not in safe_dict.keys() and safeObj.date  not in excludeList:
            safe_dict[safeObj.date]=safeObj
        elif safeObj.date  not in excludeList:
            safe_dict[safeObj.date].safe_file = safe_dict[safeObj.date].safe_file + ' ' + safe
    ################################
    dateList = [key for key in safe_dict.keys()]
    dateList.sort()
    print ("*****************************************")
    print ("Number of dates : " +str(len(dateList)))
    print ("List of dates : ")
    print (dateList)
    ################################
    #get the overlap lat and lon bounding box
    S=[]
    N=[]
    W=[]
    E=[]
    safe_dict_bbox={}
    print ('date      south      north')
    for date in dateList:
        #safe_dict[date].get_lat_lon()
        safe_dict[date].get_lat_lon_v2()
        #safe_dict[date].get_lat_lon_v3(inps)
        S.append(safe_dict[date].SNWE[0])
        N.append(safe_dict[date].SNWE[1])
        W.append(safe_dict[date].SNWE[2])
        E.append(safe_dict[date].SNWE[3])
        print (date , safe_dict[date].SNWE[0],safe_dict[date].SNWE[1])
        if inps.bbox is not None:
            if safe_dict[date].SNWE[0] <= bbox[0] and safe_dict[date].SNWE[1] >= bbox[1]:
                safe_dict_bbox[date] = safe_dict[date]
    print ("*****************************************")
    print ("The overlap region among all dates (based on the preview kml files):")
    print (" South   North   East  West ")
    print (max(S),min(N),max(W),min(E))
    print ("*****************************************")
    if max(S) > min(N):
        print ("""WARNING: 
           There might not be overlap between some dates""")
        print ("*****************************************")
    ################################
    print ('All dates')
    print (dateList)
    if inps.bbox is not None:
        safe_dict = safe_dict_bbox
        dateList = [key for key in safe_dict.keys()]
        dateList.sort()
        print ('dates covering the bbox')
        print (dateList)
  
    if inps.master_date is None: 
        inps.master_date = dateList[0]
        print ("The master date was not chosen. The first date is considered as master date.")
  
    print ("")
    print ("All SLCs will be coregistered to : " + inps.master_date)
  
    slaveList = [key for key in safe_dict.keys()]
    slaveList.sort()
    slaveList.remove(inps.master_date)
    print ("slave dates :")
    print (slaveList)
    print ("")

    return dateList, inps.master_date, slaveList, safe_dict
    
def selectNeighborPairs(dateList, num_connections):

    pairs = []
    if num_connections == 'all':
        num_connections = len(dateList) - 1
    else:
        num_connections = int(num_connections)

    num_connections = num_connections + 1
    for i in range(len(dateList)-1):
        for j in range(i+1,i + num_connections):
            if j<len(dateList):
                pairs.append((dateList[i],dateList[j]))
    return pairs


########################################
# Below are few workflow examples. 

def slcStack(inps, acquisitionDates, stackMasterDate, slaveDates, safe_dict, updateStack, pairs, processingmethod, mergeSLC=False):
    #############################
    i=0

    i+=1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i))
    if not updateStack:
        runObj.unpackStackMasterSLC(safe_dict)
    runObj.unpackSlavesSLC(stackMasterDate, slaveDates, safe_dict)
    runObj.finalize()
   
    i+=1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i))
    runObj.averageBaseline(stackMasterDate, slaveDates)
    runObj.finalize()

    if inps.coregistration in ['NESD', 'nesd']:
        if not updateStack:
            i+=1
            runObj = run()
            runObj.configure(inps, 'run_' + str(i))
            runObj.extractOverlaps()
            runObj.finalize()

        i+=1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i))
        runObj.overlap_geo2rdr_resample(slaveDates)
        runObj.finalize()

        i+=1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i))
        if updateStack:
            runObj.pairs_misregistration(slaveDates, safe_dict)
        else:
            runObj.pairs_misregistration(acquisitionDates, safe_dict)
        runObj.finalize()

        i+=1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i))
        runObj.timeseries_misregistration()
        runObj.finalize()

    i+=1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i))
    runObj.geo2rdr_resample(slaveDates)
    runObj.finalize()

    i+=1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i))
    runObj.extractStackValidRegion()
    runObj.finalize()

    if mergeSLC:
        i+=1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i))
        runObj.mergeMaster(stackMasterDate, virtual = 'False')
        runObj.mergeSlaveSLC(slaveDates, virtual = 'False')
        runObj.finalize()
    
    if processingmethod=='squeesar':
        
        i+=1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i))
        runObj.extractOverlaps()            # will be modified then
        runObj.finalize()
        
        i+=1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i))
        runObj.extractOverlaps()            # will be modified then
        runObj.finalize()
    
        i+=1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i))
        runObj.burstIgram_mergeBurst(acquisitionDates, safe_dict, pairs)
        runObj.finalize()
    
        i+=1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i))
        runObj.filter_coherence(pairs)
        runObj.finalize()
    
        i+=1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i))
        runObj.unwrap(pairs)
        runObj.finalize()

    return i
   
def checkCurrentStatus(inps):
    acquisitionDates, stackMasterDate, slaveDates, safe_dict = get_dates(inps)
    coregSLCDir = os.path.join(inps.work_dir, 'coreg_slaves')
    stackUpdate = False
    if os.path.exists(coregSLCDir):
        coregSlaves = glob.glob(os.path.join(coregSLCDir, '*'))
        coregSLC = [os.path.basename(slv) for slv in coregSlaves]
        coregSLC.sort()
        if len(coregSLC)>0:
            print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
            print('')
            print('An existing stack with following coregistered SLCs was found:')
            print(coregSLC)
            print('')
            print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')

        else:
            pass

        newAcquisitions = list(set(slaveDates).difference(set(coregSLC)))
        newAcquisitions.sort()
        if len(newAcquisitions)>0:
            print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
            print('')
            print('New acquisitions was found: ')
            print(newAcquisitions)
            print('')
            print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
        else:
            print('         *********************************           ')
            print('                 *****************           ')
            print('                     *********           ')
            print('Warning:')
            print('The stack already exists. No new acquisition found to update the stack.')
            print('')
            print('                     *********           ')
            print('                 *****************           ')
            print('         *********************************           ')
            sys.exit(1)

        numSLCReprocess = 2*int(inps.num_overlap_connections)
        if numSLCReprocess > len(slaveDates):
            numSLCReprocess = len(slaveDates)

        latestCoregSLCs =  coregSLC[-1*numSLCReprocess:]
        latestCoregSLCs_original = list(set(slaveDates).intersection(set(latestCoregSLCs)))
        if len(latestCoregSLCs_original) < numSLCReprocess:
            raise Exception('The original SAFE files for latest {0} coregistered SLCs is needed'.format(numSLCReprocess))

        print ('Last {0} coregistred SLCs to be updated: '.format(numSLCReprocess), latestCoregSLCs)

        slaveDates = latestCoregSLCs + newAcquisitions
        slaveDates.sort()
    
        acquisitionDates = slaveDates.copy()
        acquisitionDates.append(stackMasterDate)
        acquisitionDates.sort()
        print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
        print('')
        print('acquisitions used in this update: ')
        print('')
        print(acquisitionDates)
        print('')
        print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
        print('')
        print('stack master:')
        print('')
        print(stackMasterDate)
        print('')
        print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
        print('')
        print('slave acquisitions to be processed: ')
        print('')
        print(slaveDates)
        print('')
        print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
        safe_dict_new={}
        for d in acquisitionDates:
            safe_dict_new[d] = safe_dict[d]
        safe_dict = safe_dict_new
        stackUpdate = True
    else:
        print('No existing stack was identified. A new stack will be generated.')

    return acquisitionDates, stackMasterDate, slaveDates, safe_dict, stackUpdate


def editconfigsq(inps):
    slcdir = inps.slc_dirname
    
    pn = slcdir.split('/SLC')
    prn = pn[0].split('/')
    prjn = prn[-1]
    rundir = slcdir.split('SLC')[0]+'run_files'
    rname = rundir+'/run_10'
    with open(rname,'w+') as z:
        line = 'crop_sentinel.py '+' $TE/'+prjn+'.template \n'
        z.write(line)
    z.close()
    rname = rundir+'/run_11'
    with open(rname,'w+') as z:
        line = 'sentinel_squeesar.py '+' $TE/'+prjn+'.template \n'
        z.write(line)
    z.close()

    confdir = slcdir.split('SLC')[0] + 'configs'

    #confmerg = fnmatch.filter(os.listdir(confdir), "config_merge_2*")
    #for t in confmerg:
    #    mrname = confdir + '/' + t
    #    with open(mrname, 'r+') as g:
    #        new_m = g.readlines()
    #        g.seek(0)
    #        ln = 0
    #        for line in new_m:
    #           if "multilook :" in line:
    #                lx = ln
    #            ln += 1
    #        new_m[lx] = 'multilook : True \n'
    #    g.close()
    #    with open(mrname,'w') as f:
    #        for line in new_m:
    #            f.write(line)
    #    f.close()

    conflist = fnmatch.filter(os.listdir(confdir), "config_igram_2*")
    print (conflist)

    for t in conflist:
        cname = confdir+'/'+t
        with open(cname,'r+') as f:
            new_f = f.readlines()
            f.seek(0)
            ln = 0
            for line in new_f:
                if "[Function-2]" in line:
                    lx = ln
                else:
                    ln += 1
                if "multilook :" in line:
                    lmul = line
                    lx += 1
                if "range_looks" in line:
                   lrange = line
                   lx += 1
                if "azimuth_looks" in line:
                   laz = line
                   lx += 1
            new_f = new_f[0:lx]
            new_f[4]='generateIgram_sq : \n'
            l5 = new_f[5]
            print ('l5: ',l5)
            if "/master" in l5:
                l5_1 = l5.split('/master')
            else:
                l5_1 = l5.split('/coreg_slaves')
                l5 = l5_1[0] + '/merged/SLC'
                if l5_1[1]:
                   l5 = l5 + l5_1[1]
            l6 = new_f[6]
            l6_1 = l6.split('/coreg_slaves')
            l6 = l6_1[0]+'/merged/SLC'+l6_1[1]
            l7 = new_f[7]
            l7_1 = l7.split('/interferograms/')
            l7 = l7_1[0]+'/merged/interferograms/'+l7_1[1]
            master = l7_1[-1].split('_')[0]
            if '/master' in l5:
                l5 = l5_1[0] + '/merged/SLC/'+master+' \n' 
            new_f[5] = l5
            new_f[6] = l6
            new_f[7] = l7
            new_f[13] = lmul
            new_f[14] = lrange
            new_f[15] = laz
            print (new_f)
        f.close()

        with open(cname,'w') as f:
            for line in new_f:
                f.write(line)
        f.close()
    return confdir


def main(iargs=None):

    inps = cmdLineParse(iargs)
    if os.path.exists(os.path.join(inps.work_dir, 'run_files')):
        print('')
        print('**************************')
        print('run_files folder exists.')
        print(os.path.join(inps.work_dir, 'run_files'), ' already exists.') 
        print('Please remove or rename this folder and try again.')
        print('')
        print('**************************')
        sys.exit(1)

    if inps.workflow not in ['interferogram', 'offset', 'correlation', 'slc']:
        print('')
        print('**************************')
        print('Error: workflow ', inps.workflow, ' is not valid.')
        print('Please choose one of these workflows: interferogram, offset, correlation, slc')
        print('Use argument "-W" or "--workflow" to choose a specific workflow.')
        print('**************************')
        print('')
        sys.exit(1)

    acquisitionDates, stackMasterDate, slaveDates, safe_dict, updateStack = checkCurrentStatus(inps)

    if updateStack:
        print('')
        print('Updating an existing stack ...')
        print('')
    if updateStack:
        pairs = selectNeighborPairs(slaveDates, inps.num_connections)
    else:
        pairs = selectNeighborPairs(acquisitionDates, inps.num_connections)


    print ('*****************************************')
    print ('Coregistration method: ', inps.coregistration )
    print ('Workflow: ', inps.workflow)
    print ('*****************************************')
    if inps.workflow == 'slc':
        slcStack(inps, acquisitionDates, stackMasterDate, slaveDates, safe_dict, updateStack, pairs, inps.ProcessingMethod, mergeSLC=True)
        if inps.ProcessingMethod == 'squeesar':
                editconfigsq(inps)

if __name__ == "__main__":

  # Main engine  
  main()







