"""
Author:    Alex Walter
Date:      Jul 3, 2016


This is a GUI class for real time control of the DARKNESS instrument. 
 - show realtime image
 - show realtime pixel timestreams (see PixelTimestreamWindow.py)
 - start/end observations
 - organize how data is saved to disk
 - pull telescope info
 - save header information
 
 CLASSES:
    MkidDashboard - main GUI
    ImageSearcher - searches for new images on ramdisk
    ConvertPhotonsToRGB - converts a 2D list of photon counts to a QImage
 """
 
 
import os, sys, time, struct, traceback
import binascii
from socket import inet_aton
from functools import partial
import subprocess
import numpy as np
import ConfigParser
from PyQt4 import QtCore
from PyQt4.QtCore import Qt
from PyQt4 import QtGui
from PyQt4.QtGui import *
from PixelTimestreamWindow import PixelTimestreamWindow
from LaserControl import LaserControl
from Telescope import *
import casperfpga
from Roach2Controls import Roach2Controls

class ImageSearcher(QtCore.QObject):     #Extends QObject for use with QThreads
    """
    This class looks for binary '.img' files spit out by the PacketMaster2 c program on the ramdisk
    
    When it finds an image, it grabs the data, parses it into an array, and emits an imageFound signal
    Optionally, it deletes the data on the ramdisk so it doesn't fill up
    
    SIGNALS
        imageFound - emits when an image is found
        finished - emits when self.search is set to False
    """
    imageFound = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal()
    
    def __init__(self, path, nCols, nRows, parent=None):
        """
        INPUTS:
            path - path to the ramdisk where PacketMaster2 places the image files
            nCols - Number of columns in image (for DARKNESS its 80)
            nRows - for DARKNESS its 125
            parent - Leave as None so that we can add to new thread
        """
        super(QtCore.QObject, self).__init__(parent)
        self.path = path
        self.nCols = nCols
        self.nRows= nRows
        self.search=True
        
    def checkDir(self, removeOldFiles=False):
        """
        Infinite loop that keeps checking directory for an image file
        When it finds an image, it parses it and emits imageFound signal
        It only returns files that have timestamps > than the last file's timestamp
        
        Loop will continue until you set self.search to False. Then it will emit finished signal
        
        INPUTS:
            removeOldFiles - remove .img and .png files after we read them
        """
        self.search=True
        latestTime = time.time()-.5
        while self.search:
            flist = []
            for f in os.listdir(self.path):
                if f.endswith(".img"):
                    if float(f.split('.')[0]) > latestTime:
                        flist.append(f)
                    elif removeOldFiles:
                        os.remove(self.path+f)
                elif removeOldFiles and f.endswith(".png"):
                    os.remove(self.path+f)
            if len(flist)>0:
                flist.sort()
                for f in flist:
                    latestTime = float(f.split('.')[0])+.1
                    try:
                        image = self.readBinToList(self.path+f)
                        self.imageFound.emit(image)
                        time.sleep(.01) #Give image time to process before sending next one (not really needed)
                    except:
                        print self.path+f
                        traceback.print_exc()
                    if removeOldFiles:
                        os.remove(self.path+f)
        self.finished.emit()
    
    def readBinToList(self,fn):
        """
        Parses the binary image file into a numpy array
        
        INPUTS:
            fn - full filename of image file
        """
        #fin = open(fn, "rb")
        #data = fin.read()
        #fmt = 'H'*(len(data)/2)   # 2 bytes per each unsigned 16 bit integer
        #fin.close()
        
        image=np.fromfile(open(fn, mode='rb'),dtype=np.uint16)
        image = np.transpose(np.reshape(image, (self.nCols, self.nRows)))
        #image = np.asarray(struct.unpack(fmt,data), dtype=np.int)
        #image=image.reshape((self.nRows,self.nCols))
        return image
        
class ConvertPhotonsToRGB(QtCore.QObject):
    """
    This class takes 2D arrays of photon counts and converts them into a QImage
    It needs to know how to map photon counts into an RGB color
    Usually just an 8bit grey color [0, 256) but also turns maxxed out pixel red
    
    SIGNALS
        convertedImage - emits when it's done converting an image
    """
    convertedImage = QtCore.pyqtSignal(object)
    
    def __init__(self, image, minCountCutoff=0,maxCountCutoff=450, logStretch=True,parent=None):
        """
        INPUTS:
            image - 2D numpy array of photon counts
            minCountCutoff - anything <= this number of counts will be black
            maxCountCutoff - anything >= this number of counts will be red
            logStretch - see histEqualization()
        """
        super(QtCore.QObject, self).__init__(parent)
        self.image=np.copy(image)
        self.minCountCutoff=minCountCutoff
        self.maxCountCutoff=maxCountCutoff
        self.logStretch=logStretch
        self.redPixels = np.where(self.image>=self.maxCountCutoff)
        #print '#red: ',len(self.redPixels[0])
    
    def linStretch(self):
        """
        map photon count to RGB linearly
        """
        print "linear Stretch"
        self.image[np.where(self.image>self.maxCountCutoff)]=self.maxCountCutoff
        self.image[np.where(self.image<self.minCountCutoff)]=self.minCountCutoff
        
        maxVal = np.amax(self.image)
        minVal = np.amin(self.image)
        
        image2=(self.image-minVal)/(1.0*maxVal-minVal)*255.
        image2[2:4,2:4]=255
        image2[5:10,2]=0
        self.makeQPixMap(image2)
    
    def histEqualization(self):
        """
        perform a histogram Equalization. This tends to make the contrast better
        
        if self.logStretch is True the histogram uses logarithmic spaced bins
        """
        #print "Running hist"
        imShape=self.image.shape
        
        self.image[np.where(self.image>self.maxCountCutoff)]=self.maxCountCutoff
        maxVal = np.amax(self.image)
        if self.logStretch: self.minCountCutoff=max(self.minCountCutoff, 1)
        self.image[np.where(self.image<self.minCountCutoff)]=self.minCountCutoff
        
        bins=256
        if self.logStretch:
            bins = np.logspace(np.log10(self.minCountCutoff),np.log10(maxVal),256)
        imhist, imbins = np.histogram(self.image.flatten(), bins, density=True)
        
        cdf = (imhist*(imbins[1:]-imbins[:-1])).cumsum()
        cdf*=255
        
        image2 = np.interp(self.image.flatten(),imbins[:-1],cdf)
        image2=image2.reshape(self.image.shape)
        image2[np.where(self.image<=self.minCountCutoff)]=0
        self.makeQPixMap(image2)
    
    def makeQPixMap(self, image):
        """
        This function makes the QImage object
        
        INPUTS:
            image - 2D numpy array of [0,256) grey colors
        """
        image2=image.astype(np.uint32)
        redMask = np.copy(image2)
        redMask[self.redPixels] = np.uint32(0)
        #           24-32 -> A  16-24 -> R     8-16 -> G      0-8 -> B
        imageRGB = (255 << 24 | image2 << 16 | redMask << 8 | redMask).flatten()    # pack into RGBA
        q_im = QtGui.QImage(imageRGB,self.image.shape[1],self.image.shape[0],QImage.Format_RGB32)
        self.convertedImage.emit(q_im)
        
        
        
        

class MkidDashboard(QMainWindow):
    """
    Dashboard for seeing realtime DARKNESS images
    
    SIGNALS:
        newImageProcessed() - emited after processing and plotting a new image. Also whenever the current pixel selection changes
    """
    
    newImageProcessed = QtCore.pyqtSignal()
    
    def __init__(self, roachNums, configPath=None, observing=False, parent=None):
        """
        INPUTS:
            configPath - path to configuration file. See ConfigParser doc for making configuration file
            observing - indicates if packetmaster is currently writing data to disk
            parent -
        """
        self.config = ConfigParser.ConfigParser()
        if configPath is None:
            configPath = 'darkDash.cfg'
        self.config.read(configPath)
        # important variables
        self.threadPool=[]                          # Holds all the threads so they don't get lost. Also, they're garbage collected if they're attributes of self
        self.workers=[]                             # Holds workder objects corresponding to threads
        self.imageList=[]                           # Holds photon count image data
        self.timeStreamWindows = []                 # Holds PixelTimestreamWindow objects
        self.selectedPixels=set()                   # Holds the pixels currently selected
        self.observing = observing                  # Indicates if packetmaster is currently writing data to disk
        # Often overwritten variables
        self.clicking=False                         # Flag to indicate we've pressed the left mouse button and haven't released it yet
        self.pixelClicked = None                    # Holds the pixel clicked when mouse is pressed
        self.pixelCurrent = None                    # Holds the pixel the mouse is currently hovering on
        
        #Laser Controller
        laserIP=self.config.get('properties','laserIPaddress')
        laserPort=self.config.getint('properties','laserPort')
        laserReceivePort = self.config.getint('properties','laserReceivePort')
        self.laserController = LaserControl(laserIP,laserPort,laserReceivePort)
        
        #telscope TCS connection
        telescopeIP=self.config.get('properties','telescopeIPaddress')
        telescopePort=self.config.getint('properties','telescopePort')
        telescopeReceivePort = self.config.getint('properties','telescopeReceivePort')
        self.telescopeController = Telescope(telescopeIP,telescopePort,telescopeReceivePort)
        self.telescopeWindow = TelescopeWindow(self.telescopeController)
        
        #Setup GUI
        super(QMainWindow, self).__init__(parent)
        self.setWindowTitle(self.config.get('properties','instrument')+' Dashboard')
        self.create_image_widget()
        #self.obsTime = QtCore.QTime()
        self.create_dock_widget()
        self.contextMenu = QtGui.QMenu(self)    # pops up on right click
        self.create_menu()  # file menu
        
        #Connect to ROACHES and initialize network port in firmware
        self.connectToRoaches(roachNums)
        self.turnOnPhotonCapture()
        
        # Setup search for image files from cuber
        darkImageSearcher = ImageSearcher(self.config.get('properties','cuber_ramdisk'), self.config.getint('properties','ncols'),self.config.getint('properties','nrows'),parent=None)
        self.workers.append(darkImageSearcher)
        thread = QtCore.QThread(parent=self)
        self.threadPool.append(thread)
        thread.setObjectName("DARKimageSearch")
        darkImageSearcher.moveToThread(thread)
        thread.started.connect(darkImageSearcher.checkDir)
        darkImageSearcher.imageFound.connect(self.convertImage)
        darkImageSearcher.finished.connect(thread.quit)
        QtCore.QTimer.singleShot(10,self.threadPool[0].start) #start the thread after a second
        
        '''
        # Start PacketMaster2
        packetMaster_path=self.config.get('properties','packetMaster_path')
        packetMasterLog_path = self.config.get('properties','packetMasterLog_path')
        #command = "sudo nice -n -10 %s >> %s"%(packetMaster_path, packetMasterLog_path)
        command = "%s >> %s"%(packetMaster_path, packetMasterLog_path)
        print command
        QtCore.QTimer.singleShot(50,partial(subprocess.Popen,command,shell=True))
        '''
        
    def turnOffPhotonCapture(self):
        for roach in self.roachList:
            roach.fpga.write_int(self.config.get('properties','photonCapStart_reg'),0)
    
    def turnOnPhotonCapture(self):
        for roach in self.roachList:
            # set up ethernet parameters
            hostIP = self.config.get('properties','hostIP')
            dest_ip = binascii.hexlify(inet_aton(hostIP))
            dest_ip = int(dest_ip,16)
            roach.fpga.write_int(self.config.get('properties','destIP_reg'),dest_ip)
            roach.fpga.write_int(self.config.get('properties','wordsPerFrame_reg'),self.config.getint('properties','wordsPerFrame'))
            
            # restart gbe
            roach.fpga.write_int(self.config.get('properties','photonCapStart_reg'),0)
            roach.fpga.write_int(self.config.get('properties','phaseDumpEn_reg'),0)
            roach.fpga.write_int(self.config.get('properties','gbe64Rst_reg'),1)
            time.sleep(.01)
            roach.fpga.write_int(self.config.get('properties','gbe64Rst_reg'),0)

            # Start photon caputure
            roach.fpga.write_int(self.config.get('properties','photonCapStart_reg'),1)
        
    
    def connectToRoaches(self, roachNums):
        """
        Connect to roaches and make sure the photon port register is set
        
        We assume templar has already been run to set up the resonators
        Assume roach firmware is already running
        """
        self.roachList = []
        for roachNum in roachNums:
            ipaddress = self.config.get('Roach '+str(roachNum),'ipaddress')
            roachParamFile = self.config.get('Roach '+str(roachNum),'roachParamFile')
            roach=Roach2Controls(ipaddress, roachParamFile, True, False)
            roach.connect()
            
            roach.fpga.write_int(self.config.get('properties','photonPort_reg'), self.config.getint('properties','photonCapPort'))
            roach.fpga.write_int(self.config.get('properties','minFramePeriod_reg'),self.config.getint('properties','minFramePeriod'))
            
            # initialize beammap
            freqList = self.config.get('Roach '+str(roachNum),'freqList')
            freqs,_ = np.loadtxt(freqList,unpack=True)
            roach.generateResonatorChannels(freqs)
            beammapDict= {'feedline': self.config.getint('Roach '+str(roachNum),'feedline'),
                          'sideband': self.config.get('Roach '+str(roachNum),'sideband'),
                          'boardRange': self.config.get('Roach '+str(roachNum),'boardRange')}
            roach.loadBeammapCoords(initialBeammapDict = beammapDict)
            
            self.roachList.append(roach)

    
    def appendImage(self,image):
        """
        Save image data to memory so we can look at a timestream
        
        The number of images to keep is: self.config.getint('properties','num_images_to_save')
        Can't look back in time longer than that.
        
        Called by convertImage()
        
        INPUTS:
            image - 2D numpy array of photon counts
        """
        self.imageList.append(image)
        if len(self.imageList) > self.config.getint('properties','num_images_to_save'):
            self.imageList = self.imageList[-1*self.config.getint('properties','num_images_to_save'):]
    
    def convertImage(self,photonImage=None):
        """
        This function is automatically called when ImageSearcher object finds a new image file from cuber program
        We also call this function if we change the image processing controls like
            min/max count rate
            num_images_to_add
        
        Here we set up a converter object to parse the photon counts into an RBG QImage object
        We do this in a separate thread because it might take a while to process
        
        INPUTS:
            photonImage - 2D numpy array of photon counts
        """
        if photonImage is not None:
            # If there's new data, append it
            self.appendImage(photonImage)
            
        # Get the (average) photon count image
        numImages2Sum = self.config.getint('properties','num_images_to_add')
        numImages2Sum = min(numImages2Sum,len(self.imageList))
        image = np.sum(self.imageList[-1*numImages2Sum:],axis=0)
        minCountCutoff=self.config.getint('properties','min_count_rate')*numImages2Sum/self.config.getfloat('properties','packetmaster2_image_intTime')
        maxCountCutoff=self.config.getint('properties','max_count_rate')*numImages2Sum/self.config.getfloat('properties','packetmaster2_image_intTime')
        logStretch=True
        
        # Set up worker object and thread
        converter=ConvertPhotonsToRGB(image,minCountCutoff,maxCountCutoff,logStretch)
        self.workers.append(converter)                       #Need local reference or else signal is lost!
        thread = QtCore.QThread(parent=self)
        thread_num=len(self.threadPool)
        thread.setObjectName("convertImage_"+str(thread_num))
        self.threadPool.append(thread)                      #Need to have local reference to thread or else it will get lost!
        converter.moveToThread(thread)
        thread.started.connect(converter.histEqualization)
        #thread.started.connect(converter.linStretch)
        converter.convertedImage.connect(lambda x: thread.quit())
        converter.convertedImage.connect(self.updateImage)
        thread.finished.connect(partial(self.threadPool.remove,thread))         # delete these so we don't have a memory leak
        thread.finished.connect(partial(self.workers.remove,converter))
        
        # When it's done converting the worker will emit a convertedImage Signal
        converter.convertedImage.connect(lambda x: self.label_numIntegrated.setText(str(numImages2Sum)+'/'+self.label_numIntegrated.text().split('/')[-1]))
        thread.start()
    
    def updateImage(self, q_image):
        """
        This function is automatically called by a ConvertPhotonsToRGB object signal connection
        We don't call this function directly
        
        Add a new QPixMap to the graphicsViewItem and repaint
        It tells all the labels and timestream windows to update
        
        INPUTS:
            q_image - QImage that will be displayed on GUI
        """
        # Scale the bitmap so we can see individual pixels and add to the GraphicsViewItem
        imageScale=self.config.getint('properties','image_scale')
        q_image=q_image.scaledToWidth(q_image.width()*imageScale)
        self.grPixMap.pixmap().convertFromImage(q_image)
        
        # Resize the GUI to fit whole image
        borderSize=24   # Not sure how to get the size of the frame's border so hardcoded this for now
        imgSize = self.grPixMap.pixmap().size()
        frameSize = QtCore.QSize(imgSize.width()+borderSize,imgSize.height()+borderSize)
        self.centralWidget().resize(frameSize)
        self.resize(self.childrenRect().size())
        
        # Show image on screen!
        self.grPixMap.update()
        # Update the labels
        self.updateSelectedPixelLabels()
        self.updateCurrentPixelLabel()
        # Update any pixelTimestream windows that are listening
        self.newImageProcessed.emit()

    def mousePressed(self, event):
        """
        This function handles all mouse pressed events on the graphics scene through the QGraphicsPixMapItem
        
        It sets the following semi-important flags and variables:
            self.selectedPixels --> empty set       Unless we have the SHIFT key pressed, reset the list of selected pixels
            self.clicking --> True                  So we know we are in the midst of clicking and haven't released the mouse button
            self.pixelClicked --> clicked pixel     So we know which pixel we first clicked
            self.pixelCurrent --> clicked pixel     This is always the current pixel the mouse is hovering over. 
                                                    Also used for making the self.movingBox after the mouse moves
            self.movingBox --> QGraphicsRectItem    Temporary rectangle. We delete it and draw a new one everytime the mouse moves
            
        INPUTS:
            event - QGraphicsSceneMouseEvent
        """
        if event.button() == Qt.LeftButton:
            self.clicking=True
            x_pos = int(np.floor(event.pos().x()/self.config.getint('properties','image_scale')))
            y_pos = int(np.floor(event.pos().y()/self.config.getint('properties','image_scale')))
            print 'Clicked (' + str( x_pos ) + ' , ' + str( y_pos )+ ')'
            if QtGui.QApplication.keyboardModifiers() != QtCore.Qt.ShiftModifier:
                self.selectedPixels=set()
                self.removeAllPixelBoxLines()
            self.pixelClicked=[x_pos,y_pos]
            self.pixelCurrent=self.pixelClicked
            self.movingBox=self.drawPixelBox(self.pixelClicked)

    def mouseMoved(self, event):
        """
        All this function does is draw the little box when you're dragging the mouse
        
        This function is called everytime the mouse hovers or moves on the scene
        We use the self.clicking flag to make a box during a left click event
        
        It sets the following semi-important flags and variables:
            self.pixelCurrent --> current hover pixel         Used to make the self.movingBox
            self.movingBox --> QGraphicsRectItem        Box from the first clicked pixel (self.pixelClicked) to the current pixel (self.pixelCurrent
        
        INPUTS:
            event - QGraphicsSceneMouseEvent
        """
        x_pos = int(np.floor(event.pos().x()/self.config.getint('properties','image_scale')))
        y_pos = int(np.floor(event.pos().y()/self.config.getint('properties','image_scale')))
        if [x_pos, y_pos] != self.pixelCurrent and x_pos>=0 and y_pos>=0 and \
           x_pos<self.config.getint('properties','nCols') and \
           y_pos<self.config.getint('properties','nRows'):
               
            self.pixelCurrent=[x_pos, y_pos]
            self.updateCurrentPixelLabel()
            if self.clicking:
                try: 
                    self.grPixMap.scene().removeItem(self.movingBox)
                except: pass
                self.movingBox=self.drawPixelBox(pixel1=self.pixelClicked, pixel2=[x_pos, y_pos])
    
    def mouseReleased(self, event):
        """
        Executes when we release the mouse button. Adds the selected pixels to self.selectedPixels
        Tells everything that needs the current selected pixels to update
        
        It sets the following semi-important flags and variables:
            self.clicking --> False                     See mousePressed()
            self.movingBox --> None                     Removes the temporary box
            self.selectedPixels --> list of pixels      Used to draw selected pixel boxes
        
        INPUTS:
            event - QGraphicsSceneMouseEvent
        """
        if event.button() == Qt.LeftButton and self.clicking:
            self.clicking=False
            x_pos = int(np.floor(event.pos().x()/self.config.getint('properties','image_scale')))
            y_pos = int(np.floor(event.pos().y()/self.config.getint('properties','image_scale')))
            print 'Released (' + str( x_pos ) + ' , ' + str( y_pos )+ ')'
            
            x_start, x_end = sorted([x_pos,self.pixelClicked[0]])
            y_start, y_end = sorted([y_pos,self.pixelClicked[1]])
            x_start=max(x_start,0)  #make sure we're still inside the image
            y_start=max(y_start,0)
            x_end=min(x_end,self.config.getint('properties','nCols')-1)
            y_end=min(y_end,self.config.getint('properties','nRows')-1)
            
            newPixels = set((x,y) for x in range(x_start,x_end+1) for y in range(y_start,y_end+1))
            self.selectedPixels = self.selectedPixels | newPixels   # Union of set so there are no repeats
            try: 
                self.grPixMap.scene().removeItem(self.movingBox)
                self.movingBox=None
            except: pass
            self.updateSelectedPixelLabels()
            # Update any pixelTimestream windows that are listening
            self.newImageProcessed.emit()
            
            #self.drawContiguousPixelBoxes()
            for pixel in newPixels:
                box=self.drawPixelBox(pixel,color='cyan',lineWidth=1)
                #self.pixelBoxLines.append(box)

    
    def drawContiguousPixelBoxes(self,color='cyan',lineWidth=1):
        """
        This function should draw polygons around sets of contiguous selected pixels
        
        This is difficult...
        probably want to check if a selected pixel shares a border with another selected pixel or an unselected one
        """
        scale=self.config.getint('properties','image_scale')
        pixels = self.selectedPixels.copy()
        
        for i in range(len(self.selectedPixels)):
            pixel = pixels.pop()
        
        raise NotImplementedError
    

    def drawPixelBox(self, pixel1, pixel2=None, color='blue', lineWidth=3):
        """
        This function draws a box around pixel1
        If pixel2 is given then it draws a box with pixel1 and pixel 2 at opposite corners
        
        INPUTS:
            pixel1 - an [x, y] coordinate pair
            pixel2 - an [x, y] coordinate pair or None
            color - color of the box
            lineWidth - linewidth of box border in pixels
        """
        # Get upper left and lower right coordinate on graphics scene
        if pixel2 is None:
            pixel2=pixel1
        scale=self.config.getint('properties','image_scale')
        x_start, x_end = sorted([pixel1[0],pixel2[0]])
        y_start, y_end = sorted([pixel1[1],pixel2[1]])
        x_start=x_start*scale - 1      # start box one pixel over
        y_start=y_start*scale - 1
        x_end=x_end*scale+scale  
        y_end=y_end*scale+scale 
        x_start=max(x_start,0)  #make sure we're still inside the image
        y_start=max(y_start,0)
        x_end=min(x_end,self.config.getint('properties','nCols')*scale)
        y_end=min(y_end,self.config.getint('properties','nRows')*scale)
        width = x_end-x_start
        height = y_end-y_start
        
        # set up the QPen for drawing the box
        q_color=QColor()
        q_color.setNamedColor(color)
        q_pen = QPen(q_color)
        q_pen.setWidth(lineWidth)
        # Draw!
        pixelBox=self.grPixMap.scene().addRect(x_start,y_start,width,height,q_pen)
        return pixelBox

    def removeAllPixelBoxLines(self):
        """
        This function removes all QGraphicsItems (except the QGraphicsPixMapItem which holds our image) from the scene
        """
        for item in self.grPixMap.scene().items():
            if type(item) != QGraphicsPixmapItem:
                self.grPixMap.scene().removeItem(item)
    
    def getPixCountRate(self, pixelList, numImages2Sum=None):
        """
        Fet the count rate of a list of pixels.
        Can be slow :( 
        Might want to move this to a new thread in future...
        
        INPUTS:
            pixelList - a list or numpy array of pixels (not a set)
            numImages2Sum - average over this many of the last few images. If None, use the number specified on the GUI int Time box
        """
        if len(pixelList)==0:
            return 0
        if numImages2Sum is None or numImages2Sum<1:
            numImages2Sum = self.config.getint('properties','num_images_to_add')
        numImages2Sum = min(numImages2Sum,len(self.imageList))
        image = np.sum(self.imageList[-1*numImages2Sum:],axis=0)
        pixelList=np.asarray(pixelList)
        val = np.sum(np.asarray(image)[[pixelList[:,1],pixelList[:,0]]])
        return val/(1.*numImages2Sum)
    
    def updateSelectedPixelLabels(self):
        """
        This updates the labels showing the selected pixel total count rate. Can be slow ...
        
        This function is called whenever the mouse releases and when new image data is processed
        """
        if len(self.selectedPixels) > 0:
            pixels = np.asarray([[p[0],p[1]] for p in self.selectedPixels])
            val=self.getPixCountRate(pixels)
            self.label_selectedPixValue.setText('Selected Pix : '+str(np.round(val,2))+' #/second')

    def updateCurrentPixelLabel(self):
        """
        This updates the labels showing the current pixel we're hovering over
        This is usually fast enough as long as we aren't averaging over too many images
        
        This function is called when we hover to a new pixel or the image updates
        """
        if self.pixelCurrent != None:
            val=self.getPixCountRate([self.pixelCurrent])
            self.label_pixelInfo.setText('(' + str(self.pixelCurrent[0]) + ' , ' + str(self.pixelCurrent[1]) +') : '+str(np.round(val,2))+' #/second')
        
    def showContextMenu(self, point):
        """
        This function is called on a right click
        
        We don't need to clear and add the action everytime but, eh
        """
        self.contextMenu.clear()
        self.contextMenu.addAction('Plot Timestream',self.plotTimestream)
        self.contextMenu.exec_(self.sender().mapToGlobal(point))       # Need to reference to global coordinate system
    
    def plotTimestream(self):
        """
        This function is called when the user clicks on the Plot Timestream action in the context menu
        
        It pops up a window showing the selected pixel's timestream
        """
        if len(self.selectedPixels) > 0:
            pixels = np.asarray([[p[0],p[1]] for p in self.selectedPixels])
        else: pixels=[self.pixelCurrent]
        
        window = PixelTimestreamWindow(pixels, parent=self)
        self.timeStreamWindows.append(window)
        window.closeWindow.connect(partial(self.timeStreamWindows.remove, window))    # remove from list if the window is closed
        window.show()
    
    def startObs(self):
        """
        When we start to observe we have to:
            - switch Firmware into photon collect mode
            - write START file to RAM disk for PacketMaster2
        """
        if not self.observing:
            self.observing=True
            self.button_obs.setEnabled(False)
            self.button_stop.setEnabled(True)
            
            self.turnOnPhotonCapture()
            #for roach in self.roachList:
            #    # restart gbe
            #    roach.fpga.write_int(self.config.get('properties','photonCapStart_reg'),0)
            #    roach.fpga.write_int(self.config.get('properties','phaseDumpEn_reg'),0)
            #    roach.fpga.write_int(self.config.get('properties','gbe64Rst_reg'),1)
            #    time.sleep(.1)
            #    roach.fpga.write_int(self.config.get('properties','gbe64Rst_reg'),0)
            #    # start photon capture
            #    roach.fpga.write_int(self.config.get('properties','photonCapStart_reg'),1)
            
            data_path = self.config.get('properties','data_dir')
            start_file_loc = self.config.get('properties','cuber_ramdisk')
            print "Starting Obs"
            f=open(start_file_loc+'/START','w')
            f.write(data_path)
            f.close()

    
    def stopObs(self):
        """
        When we stop observing we need to:
            - Write QUIT file to RAM disk for PacketMaster2
            - switch Firmware out of photon collect mode
            - Move any log files in the ram disk to the hard disk
        """
        if self.observing:
            self.observing=False
            print "Stop Obs"
            
            stop_file_loc = self.config.get('properties','cuber_ramdisk')
            f=open(stop_file_loc+'/STOP','w')
            f.close()
            
            #Need to switch Firmware out of photon collect mode
            #wait 1 ms
            #time.sleep(.001)
            #for roach in self.roachList:
            #    roach.write_int(self.config.get('properties','photonCapStart_reg'),0)
            
            self.button_obs.setEnabled(True)
            self.button_stop.setEnabled(False)
            
            

    def laserCalClicked(self):
        laserStr = ''
        for checkbox_laser in self.checkbox_laser_list:
            if checkbox_laser.isChecked(): laserStr+='1'
            else: laserStr+='0'
        laserTime=self.spinbox_laserTime.value()
        self.laserController.toggleLaser(laserStr, laserTime)
        self.writeLog('laserCal', utc=time.time(), time=laserTime, lasers=laserStr)
        if not self.observing:
            self.startObs()
            QtCore.QTimer.singleShot(laserTime*1000+1, self.stopObs)
            
    def writeTelescopeLog(self):
        telescopeDict = self.telescopeController.getAllTelescopeInfo(self.textbox_target.text())
        self.writeLog('telescope',**telescopeDict)
    
    def writeLog(self, target=None, *args, **kwargs):
        """
        Writes a log file
        The file is named 'UNIXTIME_target.log'
        
        If we're observing, write the file to the ramdisk
        Otherwise, write to harddrive
        
        INPUTS:
            target - name of the target star
            args - list of things to write to file
            kwargs - list of 'keyword: values' to write to file
        """
        if self.observing: path = self.config.get('properties','log_ramdisk')
        else: path = self.config.get('properties','log_dir')
        currentTime=int(time.time())
        if target is None or len(target)<1: fn = str(currentTime)+'.log'
        else: fn = str(currentTime)+'_'+str(target)+'.log'
        f=open(path+fn,'a')
        for arg in args:
            f.write(str(arg))
            f.write('\n')
        for key in kwargs:
            f.write("%s: %s" % (key, str(kwargs[key])))
            f.write('\n')
        f.close()
    
    def moveLogFiles(self):
        '''
        When we're done, move any log files in the ramdisk over to the data directory
        We write log files to ram disk when we're collecting data so we don't slow down the hard disk writes
        '''
        ramdiskLog_path = self.config.get('properties','log_ramdisk')
        log_path = self.config.get('properties','log_dir')
        
        command = 'mv %s*.log %s'%(ramdiskLog_path, log_path)
        print command
        proc = subprocess.Popen(command,shell=True)
        proc.wait()
    
    def create_dock_widget(self):
        """
        Add buttons and controls
        """
        obs_dock_widget = QDockWidget(self)
        obs_dock_widget.setFeatures(QDockWidget.NoDockWidgetFeatures)
        obs_widget=QWidget(obs_dock_widget)
        
        # Current time label
        label_currentTime = QLabel("UTC: ")
        getCurrentTime = QtCore.QTimer(self)
        getCurrentTime.setInterval(997) # prime number :)
        def updateCurrentTime(): label_currentTime.setText("UTC: "+str(time.time()))
        getCurrentTime.timeout.connect(updateCurrentTime)
        getCurrentTime.start()
        # Mkid data directory
        label_dataDir = QLabel('Data Dir:')
        dataDir = self.config.get('properties','data_dir')
        textbox_dataDir = QLineEdit()
        textbox_dataDir.setText(dataDir)
        textbox_dataDir.textChanged.connect(partial(self.changedSetting,'data_dir'))
        textbox_dataDir.setEnabled(False)
        # Start observing button
        self.button_obs = QPushButton("Start Observing")
        font = self.button_obs.font()
        font.setPointSize(24)
        self.button_obs.setFont(font)
        self.button_obs.setEnabled(not self.observing)
        self.button_obs.clicked.connect(self.startObs)
        # Stop observing button
        self.button_stop = QPushButton("Stop Observing")
        self.button_stop.setEnabled(self.observing)
        self.button_stop.clicked.connect(self.stopObs)
        
        # log file
        label_target = QLabel("Target: ")
        self.textbox_target = QLineEdit()
        textbox_log = QTextEdit()
        button_log = QPushButton("Add Log File")
        
        label_autolog = QLabel("Auto log:")
        spinbox_autolog = QSpinBox()
        spinbox_autolog.setRange(0,999)
        spinbox_autolog.setValue(5)
        spinbox_autolog.setWrapping(False)
        spinbox_autolog.setCorrectionMode(QAbstractSpinBox.CorrectToNearestValue)
        spinbox_autolog.setSuffix(' minutes')
        spinbox_autolog.setToolTip("Set to 0 to stop autologging")
        
        button_log.clicked.connect(lambda x: self.writeLog(self.textbox_target.text(), textbox_log.toPlainText()))
        button_log.clicked.connect(lambda x: self.writeTelescopeLog)
        
        autoLogTimer = QtCore.QTimer(self)
        autoLogTimer.setInterval(spinbox_autolog.value()*1000*60)
        def writeLog(): self.writeLog(self.textbox_target.text(), textbox_log.toPlainText())
        autoLogTimer.timeout.connect(writeLog)
        autoLogTimer.timeout.connect(self.writeTelescopeLog)
        def changeAutoLogInterval(val):
            if val<1: autoLogTimer.stop()
            else: 
                autoLogTimer.setInterval(val*1000*60)
                autoLogTimer.start()
        spinbox_autolog.valueChanged.connect(changeAutoLogInterval)
        autoLogTimer.start()
                
        
        #==================================
        # Image settings!
        # integration Time
        integrationTime = self.config.getint('properties','num_images_to_add')
        image_int_time=self.config.getfloat('properties','packetmaster2_image_inttime')
        max_int_time=self.config.getint('properties','num_images_to_save')
        label_integrationTime = QLabel('int time:')
        spinbox_integrationTime = QSpinBox()
        spinbox_integrationTime.setRange(1,max_int_time)
        spinbox_integrationTime.setValue(integrationTime)
        spinbox_integrationTime.setSuffix(' * '+str(image_int_time)+' seconds')
        spinbox_integrationTime.setWrapping(False)
        spinbox_integrationTime.setCorrectionMode(QAbstractSpinBox.CorrectToNearestValue)
        spinbox_integrationTime.valueChanged.connect(partial(self.changedSetting,'num_images_to_add'))    # change in config file
        
        # current num images integrated
        self.label_numIntegrated = QLabel('0/'+str(integrationTime))
        spinbox_integrationTime.valueChanged.connect(lambda x: self.label_numIntegrated.setText(self.label_numIntegrated.text().split('/')[0]+'/'+str(x)))
        spinbox_integrationTime.valueChanged.connect(lambda x: QtCore.QTimer.singleShot(10,self.convertImage)) # remake current image after 10 ms
        # maxCountRate
        maxCountRate = self.config.getint('properties','max_count_rate')
        minCountRate = self.config.getint('properties','min_count_rate')
        label_maxCountRate = QLabel('max:')
        spinbox_maxCountRate = QSpinBox()
        spinbox_maxCountRate.setRange(minCountRate,2500)
        spinbox_maxCountRate.setValue(maxCountRate)
        spinbox_maxCountRate.setSuffix(' #/s')
        spinbox_maxCountRate.setWrapping(False)
        spinbox_maxCountRate.setCorrectionMode(QAbstractSpinBox.CorrectToNearestValue)
        # minCountRate
        label_minCountRate = QLabel('min:')
        spinbox_minCountRate = QSpinBox()
        spinbox_minCountRate.setRange(0,maxCountRate)
        spinbox_minCountRate.setValue(minCountRate)
        spinbox_minCountRate.setSuffix(' #/s')
        spinbox_minCountRate.setWrapping(False)
        spinbox_minCountRate.setCorrectionMode(QAbstractSpinBox.CorrectToNearestValue)
        # connections for max and min count rates
        spinbox_minCountRate.valueChanged.connect(partial(self.changedSetting,'min_count_rate'))    # change in config file
        spinbox_maxCountRate.valueChanged.connect(partial(self.changedSetting,'max_count_rate'))    # change in config file
        spinbox_minCountRate.valueChanged.connect(spinbox_maxCountRate.setMinimum)  # make sure min is always less than max
        spinbox_maxCountRate.valueChanged.connect(spinbox_minCountRate.setMaximum)
        spinbox_maxCountRate.valueChanged.connect(lambda x: QtCore.QTimer.singleShot(10,self.convertImage)) # remake current image after 10 ms
        spinbox_minCountRate.valueChanged.connect(lambda x: QtCore.QTimer.singleShot(10,self.convertImage)) # remake current image after 10 ms
        # Pixel info label
        self.label_pixelInfo=QLabel('(, ) - (, ) : 0 #/s')
        self.label_pixelInfo.setMaximumWidth(250)
        self.label_selectedPixValue = QLabel('Selected Pix : 0 #/s')
        self.label_selectedPixValue.setMaximumWidth(250)

        
        #=============================================
        # Laser control!
        self.spinbox_laserTime = QDoubleSpinBox()
        self.spinbox_laserTime.setRange(1,1800)
        self.spinbox_laserTime.setValue(300)
        self.spinbox_laserTime.setSuffix(' s')
        self.spinbox_laserTime.setSingleStep(1.)
        self.spinbox_laserTime.setWrapping(False)
        self.spinbox_laserTime.setCorrectionMode(QAbstractSpinBox.CorrectToNearestValue)
        self.spinbox_laserTime.setButtonSymbols(QAbstractSpinBox.NoButtons)
        button_laserCal = QPushButton("Start Laser Cal")
        
        numLasers = self.config.getint('properties','numLasers')
        self.checkbox_laser_list = []
        for i in range(numLasers):
            laserName = self.config.get('properties','laser'+str(i))
            checkbox_laser = QCheckBox(laserName)
            checkbox_laser.setChecked(False)
            self.checkbox_laser_list.append(checkbox_laser)
        
        button_laserCal.clicked.connect(self.laserCalClicked)
        
        #================================================
        # Layout on GUI
        
        vbox = QVBoxLayout()
        vbox.addWidget(label_currentTime)
        hbox_dataDir = QHBoxLayout()
        hbox_dataDir.addWidget(label_dataDir)
        hbox_dataDir.addWidget(textbox_dataDir)
        vbox.addLayout(hbox_dataDir)
        vbox.addWidget(self.button_obs)
        vbox.addWidget(self.button_stop)
        
        hbox_target = QHBoxLayout()
        hbox_target.addWidget(label_target)
        hbox_target.addWidget(self.textbox_target)
        #hbox_target.addStretch()
        vbox.addLayout(hbox_target)
        
        vbox.addWidget(textbox_log)
        
        hbox_log = QHBoxLayout()
        hbox_log.addWidget(label_autolog)
        hbox_log.addWidget(spinbox_autolog)
        hbox_log.addStretch()
        hbox_log.addWidget(button_log)
        vbox.addLayout(hbox_log)

        vbox.addStretch()
        
        hbox_intTime = QHBoxLayout()
        hbox_intTime.addWidget(label_integrationTime)
        hbox_intTime.addWidget(spinbox_integrationTime)
        hbox_intTime.addWidget(self.label_numIntegrated)
        hbox_intTime.addStretch()
        vbox.addLayout(hbox_intTime)
        
        hbox_CountRate = QHBoxLayout()
        hbox_CountRate.addWidget(label_minCountRate)
        hbox_CountRate.addWidget(spinbox_minCountRate)
        hbox_CountRate.addSpacing(20)
        hbox_CountRate.addWidget(label_maxCountRate)
        hbox_CountRate.addWidget(spinbox_maxCountRate)
        hbox_CountRate.addStretch()
        vbox.addLayout(hbox_CountRate)
        vbox.addWidget(self.label_pixelInfo)
        vbox.addWidget(self.label_selectedPixValue)
        
        vbox.addStretch()
        
        hbox_laser = QHBoxLayout()
        hbox_laser.addWidget(self.spinbox_laserTime)
        hbox_laser.addWidget(button_laserCal)
        vbox.addLayout(hbox_laser)
        for checkbox_laser in self.checkbox_laser_list:
            vbox.addWidget(checkbox_laser)
        
        obs_widget.setLayout(vbox)
        obs_dock_widget.setWidget(obs_widget)
        self.addDockWidget(Qt.LeftDockWidgetArea,obs_dock_widget)
    
    def create_image_widget(self):
        """
        Make image part of the GUI
        
        Heirarchy is:
                  QMainWindow
                       |
                    QFrame
                       |
                 QGraphicsView   QGraphicsPixmapItem
                        \          /         |
                         \        /       QPixmap
                       QGraphicsScene
        
        To update image:
            - Replace the QPixmap in the QGraphicsPixmapItem
            - Call update() on the QGraphicsPixmapItem to repaint the QGraphicsScene
        """
        self.imageFrame = QtGui.QFrame(parent=self)
        self.imageFrame.setFrameShape(QtGui.QFrame.Box)
        self.imageFrame.setFrameShadow(QtGui.QFrame.Sunken)
        self.imageFrame.setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Fixed)
        
        q_image=QImage(1,1,QImage.Format_Mono)
        q_image.fill(Qt.black)
        grview = QGraphicsView(self.imageFrame)
        scene = QGraphicsScene(parent=grview)
        self.grPixMap = QGraphicsPixmapItem(QPixmap(q_image), None, scene)
        self.grPixMap.mousePressEvent = self.mousePressed
        self.grPixMap.mouseMoveEvent = self.mouseMoved
        self.grPixMap.mouseReleaseEvent = self.mouseReleased
        self.grPixMap.setAcceptHoverEvents(True)
        self.grPixMap.hoverMoveEvent = self.mouseMoved
        grview.setScene(scene)
        grview.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        grview.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        grview.setContextMenuPolicy(Qt.CustomContextMenu)
        grview.customContextMenuRequested.connect(self.showContextMenu)

        
        layout=QHBoxLayout()
        layout.addWidget(grview)
        self.imageFrame.setLayout(layout)
        
        self.setCentralWidget(self.imageFrame)

    def create_menu(self):        
        self.file_menu = self.menuBar().addMenu("&File")
        quit_action = self.create_action("&Quit", slot=self.close,shortcut="Ctrl+Q", tip="Close the application")
        telescope_action = self.create_action("&Telescope Info", slot=self.telescopeWindow.show,shortcut="Ctrl+T", tip="Show Telescope Info")
        self.add_actions(self.file_menu, (telescope_action,None, quit_action))

        self.help_menu = self.menuBar().addMenu("&Help")
        about_action = self.create_action("&About", shortcut='F1',slot=self.on_about, tip='About the demo')
        self.add_actions(self.help_menu, (about_action,))
    
    def on_about(self):
        msg = "DARKNESS Dashboard!!\n"\
              "Click and drag on Pixels to select them.\n"\
              "You can select non-contiguous pixels using SHIFT.\n"\
              "Right click to plot the timestream of your selected pixels!\n\n"\
              "Author: Alex Walter\n" \
              "Date: Jul 3, 2016"
        QMessageBox.about(self, "MKID-ROACH2 software", msg.strip())
    
    def add_actions(self, target, actions):
        for action in actions:
            if action is None:
                target.addSeparator()
            else:
                target.addAction(action)

    def create_action(  self, text, slot=None, shortcut=None, 
                        icon=None, tip=None, checkable=False, 
                        signal="triggered()"):
        action = QAction(text, self)
        if icon is not None:
            action.setIcon(QIcon(":/%s.png" % icon))
        if shortcut is not None:
            action.setShortcut(shortcut)
        if tip is not None:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        if slot is not None:
            self.connect(action, QtCore.SIGNAL(signal), slot)
        if checkable:
            action.setCheckable(True)
        return action
    
    def changedSetting(self,settingID,setting,sec='properties'):
        """
        When a setting is changed, reflect the change in the config object which is shared across all GUI elements.
        
        INPUTS:
            settingID - the key in the configparser
            setting - the value
        """
        self.config.set(sec,settingID,str(setting))
        #If we don't force the setting value to be a string then the configparser has trouble grabbing the value later on for some unknown reason
        newSetting = self.config.get(sec,settingID)
        print 'setting ',settingID,' to ',newSetting
        
    def closeEvent(self, event):
        """
        Clean up before closing
        """
        if self.observing:
            self.stopObs()
        quit_file_loc = self.config.get('properties','cuber_ramdisk')
        f=open(quit_file_loc+'/QUIT','w')   # tell packetmaster to end
        f.close()
        self.workers[0].search=False    # stop searching for new images
        del self.grPixMap               # Get segfault if we don't delete this. Something about signals in the queue trying to access deleted objects...
        for thread in self.threadPool:  # They should all be done at this point, but just in case
            thread.quit()
        for window in self.timeStreamWindows:
            window.close()
        self.turnOffPhotonCapture()     # stop sending photon packets
        self.telescopeWindow._want_to_close=True
        self.telescopeWindow.close()
        
        self.moveLogFiles()             # Move any log files in the ramdisk to the hard drive
        self.hide()
        time.sleep(1)
        
        QtCore.QCoreApplication.instance().quit()

def main():
    app = QApplication(sys.argv)
    try: roachNums = np.asarray(sys.argv[1:],dtype=np.int)
    except: pass
    if len(sys.argv[1:]) == 2:
        if sys.argv[1] == '-a' or sys.argv[1] == '-all':
            roachNums = np.arange(int(sys.argv[2]),dtype=np.int)
        elif sys.argv[2] == '-a' or sys.argv[2] == '-all':
            roachNums = np.arange(int(sys.argv[1]),dtype=np.int)
    form = MkidDashboard(roachNums)
    form.show()
    app.exec_()


if __name__ == "__main__":
    main()
        
        
        
        
        
        
        
        
        
        
        
