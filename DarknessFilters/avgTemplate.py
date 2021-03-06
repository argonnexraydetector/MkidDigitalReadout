from matplotlib import rcParams, rc
import numpy as np
import sys
from fitFunctions import gaussian
import scipy.interpolate
import scipy.signal
from baselineIIR import IirFilter

# common setup for matplotlib
params = {'savefig.dpi': 300, # save figures to 300 dpi
          'axes.labelsize': 14,
          'text.fontsize': 14,
          'legend.fontsize': 14,
          'xtick.labelsize': 14,
          'ytick.major.pad': 6,
          'xtick.major.pad': 6,
          'ytick.labelsize': 14}
# use of Sans Serif also in math mode
rc('text.latex', preamble='\usepackage{sfmath}')

rcParams.update(params)

import matplotlib.pyplot as plt
import numpy as np
import os
import struct

def calcThreshold(phase,Nsigma=2.5,nSamples=5000):
    n,bins= np.histogram(phase[:nSamples],bins=100)
    n = np.array(n,dtype='float32')/np.sum(n)
    tot = np.zeros(len(bins))
    for i in xrange(len(bins)):
        tot[i] = np.sum(n[:i])
    med = bins[np.abs(tot-0.5).argmin()]
    thresh = bins[np.abs(tot-0.05).argmin()]
    threshold = int(med-Nsigma*abs(med-thresh))
    return threshold

        
def oldBaseFilter(data,alpha=0.08):
    #construct IIR
    alpha = 0.08
    numCoeffs = np.zeros(31)
    numCoeffs[30] = alpha

    denomCoeffs = np.zeros(11)
    denomCoeffs[0] = 1
    denomCoeffs[10] = -(1-alpha)
    baselines = scipy.signal.lfilter(numCoeffs,denomCoeffs,data)
    return baselines

def sigmaTrigger(data):
    #deadtime in ticks (us)
    
    data = np.array(data)

    #threshold = calcThreshold(data[0:2000])
    dataSubBase = data - baselines
    derivative = np.diff(data)
    peakHeights = []
    t = 0
    negDeriv = derivative <= 0
    posDeriv = np.logical_not(negDeriv)
   
    triggerBooleans = dataSubBase[nNegDerivChecks:-2] < threshold

    negDerivChecksSum = np.zeros(len(negDeriv[0:-nNegDerivChecks-1]))
    for i in range(nNegDerivChecks):
        negDerivChecksSum += negDeriv[i:i-nNegDerivChecks-1]
    peakCondition0 = negDerivChecksSum >= nNegDerivChecks-negDerivLenience
    peakCondition1 = np.logical_and(posDeriv[nNegDerivChecks:-1],posDeriv[nNegDerivChecks+1:])
    peakCondition01 = np.logical_and(peakCondition0,peakCondition1)
    peakBooleans = np.logical_and(triggerBooleans,peakCondition01)
        
    try:
        peakIndices = np.where(peakBooleans)[0]+nNegDerivChecks
        i = 0
        p = peakIndices[i]
        while p < peakIndices[-1]:
            peakIndices = peakIndices[np.logical_or(peakIndices-p > deadtime , peakIndices-p <= 0)]#apply deadtime
            i+=1
            if i < len(peakIndices):
                p = peakIndices[i]
            else:
                p = peakIndices[-1]
    except IndexError:
        return np.array([]),np.array([]),np.array([])
        
        
    peakHeights = data[peakIndices]
    peakBaselines = baselines[peakIndices]
    return peakIndices,peakHeights,peakBaselines

def detectPulses(sample,threshold,baselines,deadtime=10,nNegDerivChecks=10,negDerivLenience=1):
    #deadtime in ticks (us)
    data = np.array(sample)

    #threshold = calcThreshold(data[0:2000])
    dataSubBase = data - baselines
    derivative = np.diff(data)
    peakHeights = []
    t = 0
    negDeriv = derivative <= 0
    posDeriv = np.logical_not(negDeriv)
   
    triggerBooleans = dataSubBase[nNegDerivChecks:-2] < threshold

    negDerivChecksSum = np.zeros(len(negDeriv[0:-nNegDerivChecks-1]))
    for i in range(nNegDerivChecks):
        negDerivChecksSum += negDeriv[i:i-nNegDerivChecks-1]
    peakCondition0 = negDerivChecksSum >= nNegDerivChecks-negDerivLenience
    peakCondition1 = np.logical_and(posDeriv[nNegDerivChecks:-1],posDeriv[nNegDerivChecks+1:])
    peakCondition01 = np.logical_and(peakCondition0,peakCondition1)
    peakBooleans = np.logical_and(triggerBooleans,peakCondition01)
        
    try:
        peakIndices = np.where(peakBooleans)[0]+nNegDerivChecks
        i = 0
        p = peakIndices[i]
        while p < peakIndices[-1]:
            peakIndices = peakIndices[np.logical_or(peakIndices-p > deadtime , peakIndices-p <= 0)]#apply deadtime
            i+=1
            if i < len(peakIndices):
                p = peakIndices[i]
            else:
                p = peakIndices[-1]
    except IndexError:
        return np.array([]),np.array([]),np.array([])
        
        
    peakHeights = data[peakIndices]
    peakBaselines = baselines[peakIndices]
    return peakIndices,peakHeights,peakBaselines


def oldDetectPulses(sample,threshold,baselines):
    filtered = np.array(sample)

    #threshold = calcThreshold(filtered[0:2000])
    filtered -= baselines
    derivative = np.diff(filtered)
    peakHeights = []
    t = 0
    negDeriv = derivative <= 0
    posDeriv = np.logical_not(negDeriv)

    triggerBooleans = filtered[1:-2] < threshold
    peakCondition1 = np.logical_and(negDeriv[0:-2],posDeriv[1:-1])
    peakCondition2 = np.logical_and(triggerBooleans,posDeriv[2:])
    peakBooleans = np.logical_and(peakCondition1,peakCondition2)
    try:
        peakIndices = np.where(peakBooleans)[0]+1
        i = 0
        p = peakIndices[i]
        deadtime=10#us
        while p < peakIndices[-1]:
            peakIndices = peakIndices[np.logical_or(peakIndices-p > deadtime , peakIndices-p <= 0)]#apply deadtime
            i+=1
            if i < len(peakIndices):
                p = peakIndices[i]
            else:
                p = peakIndices[-1]
    except IndexError:
        return np.array([]),np.array([]),np.array([])


    peakHeights = filtered[peakIndices]
    peakBaselines = baselines[peakIndices]
    return peakIndices,peakHeights,peakBaselines

rootFolder = '/Scratch/filterData/'
quietFolder = '/Scratch/filterData/20130925/blue/'

sampleRate=1e6 # 1 MHz

#roachNum = 0
#pixelNum = 51
#secs=60
#date = '20130925'
#folder = '/Scratch/filterData/20130925/blue/'
#cps=700
#bFiltered = False
#phaseFilename = os.path.join(folder,'ch_snap_r%dp%d_%dsecs_%dcps.dat'%(roachNum,pixelNum,secs,cps))
#quietFilename = os.path.join(quietFolder,'ch_snap_r%dp%d_%dsecs_%dcps.dat'%(roachNum,pixelNum,30,0))
#label='Blue'

#roachNum = 0
#pixelNum = 51
#secs=60
#folder = '/home/kids/labData/20130925/red/'
#cps=600
#bFiltered = False
#phaseFilename = os.path.join(folder,'ch_snap_r%dp%d_%dsecs_%dcps.dat'%(roachNum,pixelNum,secs,cps))
#quietFilename = os.path.join(quietFolder,'ch_snap_r%dp%d_%dsecs_%dcps.dat'%(roachNum,pixelNum,30,0))
#label='Red'

#roachNum = 0
#pixelNum = 134
#secs=5
#folder = '/home/kids/labData/20130220/'
#cps=700
#bFiltered = True
#phaseFilename = os.path.join(folder,'ch_snap_r%dp%d_%dsecs_%dcps.dat'%(roachNum,pixelNum,secs,cps))

#roachNum = 4
#pixelNum = 2
#secs=20
#folder = os.path.join(rootFolder,'20121123/')
#bFiltered = False
#phaseFilename = os.path.join(folder,'ch_snap_r%dp%d_%dsecs.dat'%(roachNum,pixelNum,secs))
##missing quiet file, so use another
#quietFilename = os.path.join(quietFolder,'ch_snap_r%dp%d_%dsecs_%dcps.dat'%(0,51,30,0))
#roachNum = 4
#pixelNum = 51
#secs=20
#cps=200 #I don't really know. let's check
#label='Red'
#folder = os.path.join(rootFolder,'20121123/')
#bFiltered = False
#phaseFilename = os.path.join(folder,'ch_snap_r%dp%d_%dsecs.dat'%(roachNum,pixelNum,secs))
##missing quiet file, so use another
#quietFilename = phaseFilename

roachNum = 4
pixelNum = 102
secs=50
cps=200 #I don't really know. let's check
date = '20121204'
label='30tap'
folder = os.path.join(rootFolder,'20121204/')
bFiltered = False
phaseFilename = os.path.join(folder,'ch_snap_r{}p{}_{}secs.dat'.format(roachNum,pixelNum,secs))
#missing quiet file, so use another
quietFilename = phaseFilename

bPlotPeaks = True
deadtime=1000

phaseFile = open(phaseFilename,'r')
quietFile = open(quietFilename,'r')
phase = phaseFile.read()
quietPhase = quietFile.read()
numQDRSamples=2**19
numBytesPerSample=4
nLongsnapSamples = numQDRSamples*2*secs
qdrValues = struct.unpack('>%dh'%(nLongsnapSamples),phase)
qdrPhaseValues = np.array(qdrValues,dtype=np.float32)*360./2**16*4/np.pi #convert from adc units to degrees
nPhaseValues=len(qdrValues)
#nPhaseValues=int(1e5)
print nPhaseValues,'us'
quietDuration = secs #or 30
quietQdrValues = struct.unpack('>%dh'%(numQDRSamples*2*quietDuration),quietPhase)
quietQdrPhaseValues = np.array(quietQdrValues,dtype=np.float32)*360./2**16*4/np.pi #convert from adc units to degrees

fig = plt.figure()
NAxes = 1
iAxes = 1
size=26
offset = 3

sampleStart = 5000
nSamples = nPhaseValues-sampleStart
thresholdLength = 5000
thresholdSigma = 2.2

sample=qdrValues[sampleStart:sampleStart+nSamples]
quietSample=quietQdrValues[sampleStart:sampleStart+thresholdLength]
#sample = np.array(qdrPhaseValues)
if bFiltered == False:
    rawdata = np.array(sample)
    quietRawdata = np.array(quietSample)
    #filter= np.loadtxt(os.path.join(rootFolder,'fir/template20121207r%d.txt'%roachNum))[pixelNum,:]
    #lpf250kHz= np.loadtxt('/Scratch/filterData/fir/lpf_250kHz.txt')
    matched30= np.loadtxt(os.path.join(rootFolder,'fir/matched_30us.txt'))
    matched100= np.loadtxt(os.path.join(rootFolder,'fir/matched100_30us.txt'))
    filter=matched30
    #data = np.correlate(filter,rawdata,mode='same')[::-1]
    data = scipy.signal.lfilter(filter,1,rawdata)
    #quietData = np.correlate(filter,quietRawdata,mode='same')[::-1]
    quietData = scipy.signal.lfilter(filter,1,quietRawdata)
    print 'filtering done'
    sys.stdout.flush()
else:
    data = np.array(sample)
    quietData = np.array(quietSample)

criticalFreq = 20 #Hz
hpSos = IirFilter(sampleFreqHz=sampleRate,criticalFreqHz=criticalFreq,btype='highpass')

f=2*np.sin(np.pi*criticalFreq/sampleRate)
Q=.7
q=1./Q
hpSvf = IirFilter(sampleFreqHz=sampleRate,numCoeffs=np.array([1,-2,1]),denomCoeffs=np.array([1+f**2, f*q-2,1-f*q]))

baselines = data - hpSvf.filterData(data)
print 'baselines done'

threshold = calcThreshold(quietData,Nsigma=thresholdSigma)
print 'threshold done'
sys.stdout.flush()

endIdx = 20*thresholdLength
if bPlotPeaks:
    ax=fig.add_subplot(NAxes,1,iAxes)
    ax.plot(rawdata[0:endIdx],'.-',color='gray',label='raw phase')
    ax.plot(data[0:endIdx],'k.-',label='optimal filtered phase')
    ax.plot(baselines[0:endIdx],'b',label='lpf baseline')
    ax.plot(baselines[0:endIdx]+threshold,'y--',label='threshold')


idx,peaks,bases = detectPulses(data,threshold,baselines,nNegDerivChecks=30,negDerivLenience=2,deadtime=deadtime)
nPeaksDetected = len(peaks)
print len(peaks),'peaks detected'
print 1.*nPeaksDetected/secs, 'cps'
sys.stdout.flush()

nPointsBefore = 100
nPointsAfter = 200


if len(peaks)>0:
    if bPlotPeaks:
        endPeakIdx = np.searchsorted(idx,endIdx)
        
        ax.plot(idx[0:endPeakIdx],peaks[0:endPeakIdx],'r.',label='detected peak')
        ax.plot(idx[0:endPeakIdx],bases[0:endPeakIdx],'g.',label='detected baseline')
        ax.set_xlabel('time (us)')
        ax.set_ylabel('phase (${}^{\circ}$)')
        #ax.set_xlim([5000,15000])
        #ax.set_title('detected peaks and baseline for ~%d cps, pixel /r%d/p%d'%(cps,roachNum,pixelNum))
        ax.legend(loc='lower right')
        iAxes+=1

    np.savez('/Scratch/dataProcessing/filterTests/sdetected_{}_r{}p{}_{}.npz'.format(date,roachNum,pixelNum,label),idx=idx,peaks=peaks,bases=bases,baselines=baselines,threshold=threshold,qdrValues=qdrValues,data=rawdata,filtered=data)
    sys.stdout.flush()

#collect records of several rawdata points before and after each peak
figHist,axHist = plt.subplots(1,1)
peakHist,peakHistBins = np.histogram(peaks-bases,bins=200,density=True)
axHist.plot(peakHistBins[0:-1],peakHist)

#looked at the histogram for 20121123/r4p56 and picked some cutoffs by eye
peakCutMask = (peaks>-7000) & (peaks<-4959)
peaksCut = peaks[peakCutMask]
idxCut = idx[peakCutMask]
basesCut = bases[peakCutMask]

records = np.zeros((len(peaksCut),nPointsBefore+nPointsAfter),dtype=np.double)
for iPeak,peak in enumerate(peaksCut):
    peakIndex = idxCut[iPeak]
#    indexAtRawMax = np.argmax(rawdata[peakIndex-10:peakIndex+10])+peakIndex-10
#    if indexAtRawMax > nPointsBefore and indexAtRawMax < len(rawdata)-nPointsAfter:
#        records[iPeak] = rawdata[indexAtRawMax-nPointsBefore:indexAtRawMax+nPointsAfter]
    if peakIndex > nPointsBefore and peakIndex < len(rawdata)-nPointsAfter:
        records[iPeak] = rawdata[peakIndex-nPointsBefore:peakIndex+nPointsAfter]
        records[iPeak] /= np.min(records[iPeak])

pulseTemplate = np.mean(records,axis=0)
fig2,ax2 = plt.subplots(1,1)
for i in xrange(10):
    ax2.plot(records[i])
fig3,ax3 = plt.subplots(1,1)
ax3.plot(pulseTemplate,'.-')
np.savez('/Scratch/dataProcessing/filterTests/rawTemplate_{}_r{}p{}'.format(date,roachNum,pixelNum))


plt.show()

