import os
import unittest
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging
import FilmDosimetryAnalysisLogic
import DataProbeLib
from slicer.util import VTKObservationMixin
from vtk.util import numpy_support
import glob


#
# Film dosimetry analysis slicelet
#
# Streamlined workflow end-user application based on 3D Slicer and SlicerRT to support
# 3D film-based radiation dosimetry.
#
# The all-caps terms correspond to data objects in the film dosimetry data flow diagram
# https://subversion.assembla.com/svn/slicerrt/trunk/FilmDosimetryAnalysis/doc/FilmDosimetryFlowchart.pdf
#

#
# FilmDosimetryAnalysisSliceletWidget
#
class FilmDosimetryAnalysisSliceletWidget:
  def __init__(self, parent=None):
    try:
      parent
      self.parent = parent

    except Exception, e:
      import traceback
      traceback.print_exc()
      logging.error("There is no parent to FilmDosimetryAnalysisSliceletWidget!")

#
# SliceletMainFrame
#   Handles the event when the slicelet is hidden (its window closed)
#
class SliceletMainFrame(qt.QDialog):
  def setSlicelet(self, slicelet):
    self.slicelet = slicelet

  def hideEvent(self, event):
    self.slicelet.disconnect()

    import gc
    refs = gc.get_referrers(self.slicelet)
    if len(refs) > 1:
      # logging.debug('Stuck slicelet references (' + repr(len(refs)) + '):\n' + repr(refs))
      pass

    slicer.filmDosimetrySliceletInstance = None
    self.slicelet = None
    self.deleteLater()

#
# FilmDosimetryAnalysisSlicelet
#
class FilmDosimetryAnalysisSlicelet(VTKObservationMixin):
  def __init__(self, parent, developerMode=False, widgetClass=None):
    VTKObservationMixin.__init__(self)

    # Set up main frame
    self.parent = parent
    self.parent.setLayout(qt.QHBoxLayout())

    self.layout = self.parent.layout()
    self.layout.setMargin(0)
    self.layout.setSpacing(0)

    self.sliceletPanel = qt.QFrame(self.parent)
    self.sliceletPanelLayout = qt.QVBoxLayout(self.sliceletPanel)
    self.sliceletPanelLayout.setMargin(4)
    self.sliceletPanelLayout.setSpacing(0)
    self.layout.addWidget(self.sliceletPanel,1)

    # For testing only (it is only visible when in developer mode)
    self.selfTestButton = qt.QPushButton("Run self-test")
    self.sliceletPanelLayout.addWidget(self.selfTestButton)
    self.selfTestButton.connect('clicked()', self.onSelfTestButtonClicked)
    if not developerMode:
      self.selfTestButton.setVisible(False)

    # Initiate and group together all panels
    self.step0_layoutSelectionCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_calibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_loadExperimentalDataCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step3_applyCalibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step4_registrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step5_CollapsibleButton = ctk.ctkCollapsibleButton()
    self.testButton = ctk.ctkCollapsibleButton()

    self.collapsibleButtonsGroup = qt.QButtonGroup()
    self.collapsibleButtonsGroup.addButton(self.step0_layoutSelectionCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step1_calibrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step2_loadExperimentalDataCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step3_applyCalibrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step4_registrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step5_CollapsibleButton)   

    self.collapsibleButtonsGroup.addButton(self.testButton)

    self.step1_calibrationCollapsibleButton.setProperty('collapsed', False)

    # Create module logic
    self.logic = FilmDosimetryAnalysisLogic.FilmDosimetryAnalysisLogic()

    # Declare member variables (selected at certain steps and then from then on for the workflow)
    self.batchFolderToParse = None
    self.opticalDensityCurve = None

    # Constants
    self.maxNumberOfCalibrationFilms = 10

    # Set observations
    self.addObserver(slicer.mrmlScene, slicer.vtkMRMLScene.NodeAddedEvent, self.onNodeAdded)
    self.addObserver(slicer.mrmlScene, slicer.vtkMRMLScene.EndImportEvent, self.onSceneEndImport)

    # Turn on slice intersections in 2D viewers
    compositeNodes = slicer.util.getNodes("vtkMRMLSliceCompositeNode*")
    for compositeNode in compositeNodes.values():
      compositeNode.SetSliceIntersectionVisibility(1)

    # Add layout widget
    self.layoutWidget = slicer.qMRMLLayoutWidget()
    self.layoutWidget.setMRMLScene(slicer.mrmlScene)
    self.parent.layout().addWidget(self.layoutWidget,2)
    self.onViewSelect(0)

    # Create slice annotations for scalar bar support
    self.sliceAnnotations = DataProbeLib.SliceAnnotations(self.layoutWidget.layoutManager())
    self.sliceAnnotations.scalarBarEnabled = 0
    self.sliceAnnotations.updateSliceViewFromGUI()

    # Set up step panels
    self.setup_Step0_LayoutSelection()
    self.setup_Step1_Calibration()
    self.setup_Step2_LoadExperimentalData()
    self.setup_Step3_ApplyCalibration()
    self.setup_Step4_Registration()
    self.setup_Step5_GammaComparison()

    if widgetClass:
      self.widget = widgetClass(self.parent)
    self.parent.show()

  #------------------------------------------------------------------------------
  # Disconnect all connections made to the slicelet to enable the garbage collector to destruct the slicelet object on quit
  def disconnect(self):
    self.selfTestButton.disconnect('clicked()', self.onSelfTestButtonClicked)
    self.step0_viewSelectorComboBox.disconnect('activated(int)', self.onViewSelect)
    self.step1_loadImageFilesButton.disconnect('clicked()', self.onLoadImageFilesButton)
    self.step1_numberOfCalibrationFilmsSpinBox.disconnect('valueChanged(int)', self.onNumberOfCalibrationFilmsSpinBoxValueChanged)
    self.step1_saveCalibrationBatchButton.disconnect('clicked()', self.onSaveCalibrationBatchButton)
    self.step1_loadCalibrationBatchButton.disconnect('clicked()', self.onLoadCalibrationBatchButton)
    self.step1_saveCalibrationFunctionToFileButton.disconnect('clicked()', self.onSaveCalibrationFunctionToFileButton)
    self.step1_addRoiButton.disconnect('clicked()', self.onAddRoiButton)
    self.step1_performCalibrationButton.disconnect('clicked()', self.onPerformCalibrationButton)
    self.step2_loadNonDicomDataButton.disconnect('clicked()', self.onLoadImageFilesButton)
    self.step2_showDicomBrowserButton.disconnect('clicked()', self.onDicomLoad)
    self.step2_experimentalFilmSpacingLineEdit.disconnect('textChanged(QString)', self.onExperimentalFilmSpacingChanged)
    self.step2_loadExperimentalDataCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_loadExperimentalDataCollapsed)
    self.step3_calibrationFunctionOrder0LineEdit.disconnect('textChanged()', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionOrder1LineEdit.disconnect('textChanged()', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionOrder2LineEdit.disconnect('textChanged()', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionExponentLineEdit.disconnect('textChanged()', self.onCalibrationFunctionLineEditChanged)
    self.step3_applyCalibrationButton.disconnect('clicked()', self.onApplyCalibrationButton)
    self.step3_loadCalibrationButton.disconnect('clicked()', self.onLoadCalibrationFunctionFromFileButton)
    self.step3_applyCalibrationCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep3_ApplyCalibrationCollapsed)
    self.step4_performRegistrationButton.disconnect('clicked()', self.onPerformRegistrationButtonClicked)

  #------------------------------------------------------------------------------
  def setup_Step0_LayoutSelection(self):
    # Layout selection step
    self.step0_layoutSelectionCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step0_layoutSelectionCollapsibleButton.text = "Layout selector"
    # self.step0_layoutSelectionCollapsibleButton.text = "Layout and mode selector"
    self.sliceletPanelLayout.addWidget(self.step0_layoutSelectionCollapsibleButton)
    self.step0_layoutSelectionCollapsibleButtonLayout = qt.QFormLayout(self.step0_layoutSelectionCollapsibleButton)
    self.step0_layoutSelectionCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step0_layoutSelectionCollapsibleButtonLayout.setSpacing(4)

    self.step0_viewSelectorComboBox = qt.QComboBox(self.step0_layoutSelectionCollapsibleButton)
    self.step0_viewSelectorComboBox.addItem("Four-up 3D + 3x2D view")
    self.step0_viewSelectorComboBox.addItem("Conventional 3D + 3x2D view")
    self.step0_viewSelectorComboBox.addItem("3D-only view")
    self.step0_viewSelectorComboBox.addItem("Axial slice only view")
    self.step0_viewSelectorComboBox.addItem("Double 3D view")
    self.step0_viewSelectorComboBox.addItem("Four-up plus plot view")
    self.step0_viewSelectorComboBox.addItem("Plot only view")
    self.step0_layoutSelectionCollapsibleButtonLayout.addRow("Layout: ", self.step0_viewSelectorComboBox)
    self.step0_viewSelectorComboBox.connect('activated(int)', self.onViewSelect)

    # Mode Selector: Radio-buttons
    self.step0_modeSelectorLayout = qt.QGridLayout()
    self.step0_modeSelectorLabel = qt.QLabel('Select mode: ')
    self.step0_modeSelectorLayout.addWidget(self.step0_modeSelectorLabel, 0, 0, 1, 1)
    self.step0_clinicalModeRadioButton = qt.QRadioButton('Clinical optical readout')
    self.step0_clinicalModeRadioButton.setChecked(True)
    self.step0_modeSelectorLayout.addWidget(self.step0_clinicalModeRadioButton, 0, 1)
    self.step0_preclinicalModeRadioButton = qt.QRadioButton('Preclinical MRI readout')
    self.step0_modeSelectorLayout.addWidget(self.step0_preclinicalModeRadioButton, 0, 2)

  #------------------------------------------------------------------------------
  def setup_Step1_Calibration(self):
    # Step 1: Load data panel
    self.step1_calibrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_calibrationCollapsibleButton.text = "1. Calibration (optional)"
    self.sliceletPanelLayout.addWidget(self.step1_calibrationCollapsibleButton)

    # Step 1 main background layout
    self.step1_calibrationLayout = qt.QVBoxLayout(self.step1_calibrationCollapsibleButton)

    #
    # Step 1.1: Load calibration data
    self.step1_1_loadCalibrationDataCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_1_loadCalibrationDataCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_1_loadCalibrationDataCollapsibleButton.text = "1.1. Load calibration data"
    self.step1_calibrationLayout.addWidget(self.step1_1_loadCalibrationDataCollapsibleButton)

    self.step1_1_loadCalibrationDataLayout = qt.QVBoxLayout(self.step1_1_loadCalibrationDataCollapsibleButton)
    self.step1_1_loadCalibrationDataLayout.setContentsMargins(12,4,4,4)
    self.step1_1_loadCalibrationDataLayout.setSpacing(4)

    #
    # Step 1.1 top sub-layout (the calibration films table needs to be updated within its own layout)
    self.step1_1_topCalibrationSubLayout = qt.QVBoxLayout()
    self.step1_1_loadCalibrationDataLayout.addLayout(self.step1_1_topCalibrationSubLayout)

    # Load data label
    self.step1_CalibrationLabel = qt.QLabel("Load calibration images (can be a new batch of images or a saved batch)")
    self.step1_CalibrationLabel.wordWrap = True
    self.step1_1_topCalibrationSubLayout.addWidget(self.step1_CalibrationLabel)

    # Load image data button
    self.step1_loadImageFilesButton = qt.QPushButton("Load image files")
    self.step1_loadImageFilesButton.toolTip = "Load calibration and flood field images.\nUsed for creating a new calibration batch"
    self.step1_loadImageFilesButton.name = "loadImageFilesButton"
    # Load saved image batch button
    self.step1_loadCalibrationBatchButton = qt.QPushButton("Load calibration batch")
    self.step1_loadCalibrationBatchButton.toolTip = "Load a saved batch of calibration films"
    self.step1_loadCalibrationBatchButton.name = "loadCalibrationFilesButton"
    # Horizontal button layout
    self.step1_loadImageButtonLayout = qt.QHBoxLayout()
    self.step1_loadImageButtonLayout.addWidget(self.step1_loadImageFilesButton)
    self.step1_loadImageButtonLayout.addWidget(self.step1_loadCalibrationBatchButton)

    self.step1_1_topCalibrationSubLayout.addLayout(self.step1_loadImageButtonLayout)

    # Add empty row
    self.step1_1_topCalibrationSubLayout.addWidget(qt.QLabel(''))

    # Assign data label
    self.step1_assignDosesLabel = qt.QLabel("Assign dose levels to films.\nNote: If selection is changed then all the following steps need to be performed again")
    self.step1_assignDosesLabel.wordWrap = True
    self.step1_1_topCalibrationSubLayout.addWidget(self.step1_assignDosesLabel)

    # Number of calibration films node selector
    self.step1_numberOfCalibrationFilmsSelectorLayout = qt.QHBoxLayout()
    self.step1_numberOfCalibrationFilmsSpinBox = qt.QSpinBox()
    self.step1_numberOfCalibrationFilmsSpinBox.value = 5
    self.step1_numberOfCalibrationFilmsSpinBox.minimum = 1
    self.step1_numberOfCalibrationFilmsSpinBox.maximum = 10
    self.step1_numberOfCalibrationFilmsSpinBox.enabled = True
    self.step1_numberOfCalibrationFilmsLabelBefore = qt.QLabel('Number of calibration films: ')
    self.step1_numberOfCalibrationFilmsSelectorLayout.addWidget(self.step1_numberOfCalibrationFilmsLabelBefore)
    self.step1_numberOfCalibrationFilmsSelectorLayout.addWidget(self.step1_numberOfCalibrationFilmsSpinBox)
    self.step1_1_topCalibrationSubLayout.addLayout(self.step1_numberOfCalibrationFilmsSelectorLayout)

    # Choose the flood field image
    self.step1_floodFieldImageSelectorComboBoxLayout = qt.QHBoxLayout()
    self.step1_floodFieldImageSelectorComboBox = slicer.qMRMLNodeComboBox()
    self.step1_floodFieldImageSelectorComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_floodFieldImageSelectorComboBox.addEnabled = True
    self.step1_floodFieldImageSelectorComboBox.removeEnabled = True
    self.step1_floodFieldImageSelectorComboBox.setMRMLScene( slicer.mrmlScene )
    self.step1_floodFieldImageSelectorComboBox.setToolTip( "Choose the flood field image" )
    self.step1_floodFieldImageSelectorComboBoxLabel = qt.QLabel('Flood field image: ')
    self.step1_floodFieldImageSelectorComboBoxLayout.addWidget(self.step1_floodFieldImageSelectorComboBoxLabel)
    self.step1_floodFieldImageSelectorComboBoxLayout.addWidget(self.step1_floodFieldImageSelectorComboBox)
    self.step1_1_topCalibrationSubLayout.addLayout(self.step1_floodFieldImageSelectorComboBoxLayout)

    #
    # Step 1.1 middle sub-layout (the calibration films table needs to be updated within its own layout)
    self.step1_1_middleCalibrationSubLayout = qt.QVBoxLayout()
    self.step1_1_loadCalibrationDataLayout.addLayout(self.step1_1_middleCalibrationSubLayout)

    self.step1_calibrationVolumeLayoutList = []
    self.step1_calibrationVolumeSelectorLabelBeforeList = []
    self.step1_calibrationVolumeSelectorCGySpinBoxList = []
    self.step1_calibrationVolumeSelectorCGyLabelList = []
    self.step1_calibrationVolumeSelectorComboBoxList = []

    # Create calibration films table
    for doseToImageLayoutNumber in xrange(self.maxNumberOfCalibrationFilms):
      self.step1_doseToImageSelectorRowLayout = qt.QHBoxLayout()
      self.step1_mainCalibrationVolumeSelectorLabelBefore = qt.QLabel('Calibration ')
      self.step1_calibrationVolumeSelectorLabelBeforeList.append(self.step1_mainCalibrationVolumeSelectorLabelBefore)

      self.doseToImageSelectorCGySpinBox = qt.QSpinBox()
      self.doseToImageSelectorCGySpinBox.minimum = 0
      self.doseToImageSelectorCGySpinBox.maximum = 10000
      self.step1_calibrationVolumeSelectorCGySpinBoxList.append(self.doseToImageSelectorCGySpinBox)

      self.doseToImageSelectorLabelMiddle = qt.QLabel(' cGy : ')
      self.step1_calibrationVolumeSelectorCGyLabelList.append(self.doseToImageSelectorLabelMiddle)

      self.doseToImageFilmSelector = slicer.qMRMLNodeComboBox()
      self.doseToImageFilmSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
      self.doseToImageFilmSelector.addEnabled = False
      self.doseToImageFilmSelector.removeEnabled = False
      self.doseToImageFilmSelector.setMRMLScene( slicer.mrmlScene )
      self.doseToImageFilmSelector.setToolTip("Choose the film image corresponding to the dose on the left")
      self.step1_calibrationVolumeSelectorComboBoxList.append(self.doseToImageFilmSelector)

      self.step1_doseToImageSelectorRowLayout.addWidget(self.step1_mainCalibrationVolumeSelectorLabelBefore)
      self.step1_doseToImageSelectorRowLayout.addWidget(self.doseToImageSelectorCGySpinBox)
      self.step1_doseToImageSelectorRowLayout.addWidget(self.doseToImageSelectorLabelMiddle)
      self.step1_doseToImageSelectorRowLayout.addWidget(self.doseToImageFilmSelector)

      self.step1_calibrationVolumeLayoutList.append(self.step1_doseToImageSelectorRowLayout)
      self.step1_1_middleCalibrationSubLayout.addLayout(self.step1_doseToImageSelectorRowLayout)

    #
    # Step 1.1 bottom sub-layout (the calibration films table needs to be updated within its own layout)
    self.step1_1_bottomCalibrationSubLayout = qt.QVBoxLayout()
    self.step1_1_loadCalibrationDataLayout.addLayout(self.step1_1_bottomCalibrationSubLayout)

    # Save batch button
    self.step1_saveCalibrationBatchButton = qt.QPushButton("Save calibration batch")
    self.step1_saveCalibrationBatchButton.toolTip = "Saves current calibration batch"
    self.step1_1_bottomCalibrationSubLayout.addWidget(self.step1_saveCalibrationBatchButton)

    # Add empty row
    self.step1_1_bottomCalibrationSubLayout.addWidget(qt.QLabel(''))

    #
    # Step 1.2: Perform calibration
    self.step1_2_performCalibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_2_performCalibrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_2_performCalibrationCollapsibleButton.text = "1.2. Perform calibration"
    self.step1_calibrationLayout.addWidget(self.step1_2_performCalibrationCollapsibleButton)
    self.step1_2_performCalibrationLayout = qt.QVBoxLayout(self.step1_2_performCalibrationCollapsibleButton)
    self.step1_2_performCalibrationLayout.setContentsMargins(12,4,4,4)
    self.step1_2_performCalibrationLayout.setSpacing(4)

    # Add ROI button
    self.step1_addRoiButton = qt.QPushButton("Add region")
    self.step1_addRoiButton.setIcon(qt.QIcon(":/Icons/AnnotationROIWithArrow.png"))
    self.step1_addRoiButton.toolTip = "Add ROI (region of interest) that is considered when measuring dose in the calibration images\n\nOnce activated, click in the center of the region to be used for calibration, then do another click to one of the corners. After that the ROI appears and can be adjusted using the colored handles."
    self.step1_2_performCalibrationLayout.addWidget(self.step1_addRoiButton)

    # Calibration button
    self.step1_performCalibrationButton = qt.QPushButton("Perform calibration")
    self.step1_performCalibrationButton.toolTip = "Finds the calibration function"
    self.step1_2_performCalibrationLayout.addWidget(self.step1_performCalibrationButton)

    # Calibration function
    self.step1_calibrationFunctionLabel = qt.QLabel('Optical density to dose calibration function: ')
    self.step1_2_performCalibrationLayout.addWidget(self.step1_calibrationFunctionLabel)

    #TODO:
    self.blankLabel = qt.QLabel('')
    self.step1_2_performCalibrationLayout.addWidget(self.blankLabel)
    # Dose calibration function label
    self.step1_2_performCalibrationFunctionLabel = qt.QLabel(" ")
    self.step1_2_performCalibrationLayout.addWidget(self.step1_2_performCalibrationFunctionLabel)

    self.step1_2_performCalibrationLayout.addWidget(self.blankLabel)

    # Save calibration function button
    self.step1_saveCalibrationFunctionToFileButton = qt.QPushButton("Save calibration function to file")
    self.step1_saveCalibrationFunctionToFileButton.toolTip = "Save calibration function for later use"
    self.step1_2_performCalibrationLayout.addWidget(self.step1_saveCalibrationFunctionToFileButton)

    self.step1_1_bottomCalibrationSubLayout.addStretch(1)

    # Step 1 sub button group
    self.step1_calibrationCollapsibleButtonGroup = qt.QButtonGroup()
    self.step1_calibrationCollapsibleButtonGroup.addButton(self.step1_1_loadCalibrationDataCollapsibleButton)
    self.step1_calibrationCollapsibleButtonGroup.addButton(self.step1_2_performCalibrationCollapsibleButton)

    self.step1_1_loadCalibrationDataCollapsibleButton.setProperty('collapsed', False)

    # Update calibration films table to set row visibilities
    self.setNumberOfCalibrationFilmsInTable(self.step1_numberOfCalibrationFilmsSpinBox.value)

    # Connections
    self.step1_loadImageFilesButton.connect('clicked()', self.onLoadImageFilesButton)
    self.step1_saveCalibrationBatchButton.connect('clicked()', self.onSaveCalibrationBatchButton)
    self.step1_loadCalibrationBatchButton.connect('clicked()', self.onLoadCalibrationBatchButton)
    self.step1_numberOfCalibrationFilmsSpinBox.connect('valueChanged(int)', self.onNumberOfCalibrationFilmsSpinBoxValueChanged)
    self.step1_addRoiButton.connect('clicked()', self.onAddRoiButton)
    self.step1_performCalibrationButton.connect('clicked()', self.onPerformCalibrationButton)
    self.step1_saveCalibrationFunctionToFileButton.connect('clicked()', self.onSaveCalibrationFunctionToFileButton)

  #------------------------------------------------------------------------------
  def setup_Step2_LoadExperimentalData(self):
  # Step 2: Load data panel
    self.step2_loadExperimentalDataCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_loadExperimentalDataCollapsibleButton.text = "2. Load experimental data"
    self.sliceletPanelLayout.addWidget(self.step2_loadExperimentalDataCollapsibleButton)

    self.step2_loadExperimentalDataCollapsibleButtonLayout = qt.QVBoxLayout(self.step2_loadExperimentalDataCollapsibleButton)
    self.step2_loadExperimentalDataCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step2_loadExperimentalDataCollapsibleButtonLayout.setSpacing(4)

    # Load data label
    self.step2_LoadDataLabel = qt.QLabel("Load all data involved in the workflow.\nNote: Can return to this step later if more data needs to be loaded")
    self.step2_LoadDataLabel.wordWrap = True
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addWidget(self.step2_LoadDataLabel)

    # Load DICOM data button
    self.step2_showDicomBrowserButton = qt.QPushButton("Load DICOM data")
    self.step2_showDicomBrowserButton.toolTip = "Load planning data (CT, dose, structures)"
    self.step2_showDicomBrowserButton.name = "showDicomBrowserButton"
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addWidget(self.step2_showDicomBrowserButton)

    # Load non-DICOM data button
    self.step2_loadNonDicomDataButton = qt.QPushButton("Load experimental film data from file")
    self.step2_loadNonDicomDataButton.toolTip = "Load experimental film image from PNG, etc."
    self.step2_loadNonDicomDataButton.name = "loadNonDicomDataButton"
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addWidget(self.step2_loadNonDicomDataButton)

    # Add empty row
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addWidget(qt.QLabel(""))

    # Assign loaded data to roles
    self.step2_assignDataLabel = qt.QLabel("Assign loaded data to roles.\nNote: If this selection is changed later then all the following steps need to be performed again")
    self.step2_assignDataLabel.wordWrap = True
    self.step2_loadExperimentalDataCollapsibleButtonLayout.addWidget(self.step2_assignDataLabel)

    self.step2_assignDataLayout = qt.QFormLayout(self.step0_layoutSelectionCollapsibleButton)
    self.step2_assignDataLayout.setSpacing(4)

    # Experimental film image selector
    self.step2_experimentalFilmSelectorComboBox = slicer.qMRMLNodeComboBox()
    self.step2_experimentalFilmSelectorComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step2_experimentalFilmSelectorComboBox.addEnabled = False
    self.step2_experimentalFilmSelectorComboBox.removeEnabled = False
    self.step2_experimentalFilmSelectorComboBox.setMRMLScene(slicer.mrmlScene)
    self.step2_experimentalFilmSelectorComboBox.toolTip = "Select the experimental film image"
    self.step2_assignDataLayout.addRow('Experimental film image: ', self.step2_experimentalFilmSelectorComboBox)

    # Experimental film resolution mm/pixel
    self.step2_experimentalFilmSpacingLineEdit = qt.QLineEdit()
    self.step2_experimentalFilmSpacingLineEdit.toolTip = "Experimental film resultion (mm/pixel)"
    self.step2_assignDataLayout.addRow('Experimental Film Resolution (mm/pixel): ', self.step2_experimentalFilmSpacingLineEdit)

    # Experimental flood field image selector
    self.step2_floodFieldImageSelectorComboBox = slicer.qMRMLNodeComboBox()
    self.step2_floodFieldImageSelectorComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step2_floodFieldImageSelectorComboBox.addEnabled = False
    self.step2_floodFieldImageSelectorComboBox.removeEnabled = False
    self.step2_floodFieldImageSelectorComboBox.setMRMLScene(slicer.mrmlScene)
    self.step2_floodFieldImageSelectorComboBox.toolTip = "Select flood film image for experimental film"
    self.step2_assignDataLayout.addRow('Flood field image (for experimental film): ', self.step2_floodFieldImageSelectorComboBox)

    # Plan dose volume selector
    self.step2_planDoseVolumeSelector = slicer.qMRMLNodeComboBox()
    self.step2_planDoseVolumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step2_planDoseVolumeSelector.addEnabled = False
    self.step2_planDoseVolumeSelector.removeEnabled = False
    self.step2_planDoseVolumeSelector.setMRMLScene(slicer.mrmlScene)
    self.step2_planDoseVolumeSelector.setToolTip("Select the planning dose volume")
    self.step2_assignDataLayout.addRow('Dose volume: ', self.step2_planDoseVolumeSelector)

    self.step2_loadExperimentalDataCollapsibleButtonLayout.addLayout(self.step2_assignDataLayout)

    # Enter plane position
    self.step2_planePositionLabel = qt.QLabel('Plane position :')
    self.step2_planePositionLineEdit = qt.QLineEdit()
    self.step2_planePositionQHBoxLayout = qt.QHBoxLayout()
    self.step2_planePositionQHBoxLayout.addWidget(self.step2_planePositionLabel)
    self.step2_planePositionQHBoxLayout.addWidget(self.step2_planePositionLineEdit)

    # Connections
    self.step2_loadNonDicomDataButton.connect('clicked()', self.onLoadImageFilesButton)
    self.step2_showDicomBrowserButton.connect('clicked()', self.onDicomLoad)
    self.step2_experimentalFilmSpacingLineEdit.connect('textChanged(QString)', self.onExperimentalFilmSpacingChanged)
    self.step2_loadExperimentalDataCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep2_loadExperimentalDataCollapsed)

  #------------------------------------------------------------------------------
  def setup_Step3_ApplyCalibration(self):
  # Step 2: Load data panel
    self.step3_applyCalibrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step3_applyCalibrationCollapsibleButton.text = "3. Apply calibration"
    self.sliceletPanelLayout.addWidget(self.step3_applyCalibrationCollapsibleButton)

    self.step3_applyCalibrationCollapsibleButtonLayout = qt.QVBoxLayout(self.step3_applyCalibrationCollapsibleButton)
    self.step3_applyCalibrationCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step3_applyCalibrationCollapsibleButtonLayout.setSpacing(4)

    # Load calibration function button
    self.step3_loadCalibrationButton = qt.QPushButton("Load calibration function from file")
    self.step3_loadCalibrationButton.toolTip = "Loads calibration function \n Function can also be added into text fields"
    self.step3_applyCalibrationCollapsibleButtonLayout.addWidget(self.step3_loadCalibrationButton)

    # Dose calibration function input fields
    self.step3_calibrationFunctionLayout = qt.QGridLayout()
    self.step3_doseLabel = qt.QLabel('Dose (cGy) = ')
    self.step3_calibrationFunctionOrder0LineEdit = qt.QLineEdit()
    self.step3_calibrationFunctionOrder0LineEdit.maximumWidth = 64
    self.step3_calibrationFunctionOrder0Label = qt.QLabel(' + ')
    self.step3_calibrationFunctionOrder1LineEdit = qt.QLineEdit()
    self.step3_calibrationFunctionOrder1LineEdit.maximumWidth = 64
    self.step3_calibrationFunctionOrder1Label = qt.QLabel(' OD + ')
    self.step3_calibrationFunctionOrder2LineEdit = qt.QLineEdit()
    self.step3_calibrationFunctionOrder2LineEdit.maximumWidth = 64
    self.step3_calibrationFunctionOrder2Label = qt.QLabel(' OD ^ ')
    self.step3_calibrationFunctionExponentLineEdit = qt.QLineEdit()
    self.step3_calibrationFunctionExponentLineEdit.maximumWidth = 42

    self.step3_calibrationFunctionLayout.addWidget(self.step3_doseLabel,0,0)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder0LineEdit,0,1)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder0Label,0,2)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder1LineEdit,0,3)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder1Label,0,4)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder2LineEdit,1,1)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionOrder2Label,1,2)
    self.step3_calibrationFunctionLayout.addWidget(self.step3_calibrationFunctionExponentLineEdit,1,3)
    self.step3_applyCalibrationCollapsibleButtonLayout.addLayout(self.step3_calibrationFunctionLayout)

    # Add empty row
    self.step3_applyCalibrationCollapsibleButtonLayout.addWidget(qt.QLabel(''))

    # Apply calibration button
    self.step3_applyCalibrationButton = qt.QPushButton("Apply calibration on experimental film")
    self.step3_applyCalibrationButton.toolTip = "Apply calibration to experimental film."
    self.step3_applyCalibrationCollapsibleButtonLayout.addWidget(self.step3_applyCalibrationButton)

    # Connections
    self.step3_applyCalibrationButton.connect('clicked()', self.onApplyCalibrationButton)
    self.step3_loadCalibrationButton.connect('clicked()', self.onLoadCalibrationFunctionFromFileButton)
    self.step3_calibrationFunctionOrder0LineEdit.connect('textChanged(QString)', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionOrder1LineEdit.connect('textChanged(QString)', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionOrder2LineEdit.connect('textChanged(QString)', self.onCalibrationFunctionLineEditChanged)
    self.step3_calibrationFunctionExponentLineEdit.connect('textChanged(QString)', self.onCalibrationFunctionLineEditChanged)
    self.step3_applyCalibrationCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep3_ApplyCalibrationCollapsed)

  #------------------------------------------------------------------------------
  def setup_Step4_Registration(self):
    # Step 2: Load data panel
    self.step4_registrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step4_registrationCollapsibleButton.text = "4. Register film to plan"
    self.sliceletPanelLayout.addWidget(self.step4_registrationCollapsibleButton)

    self.step4_registrationCollapsibleButtonLayout = qt.QVBoxLayout(self.step4_registrationCollapsibleButton)
    self.step4_registrationCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step4_registrationCollapsibleButtonLayout.setSpacing(4)
    
    # Registration label
    self.step4_registrationLabel = qt.QLabel("Register film to plan dose slice.\nSlice at specified position will be extracted and registered to experimental film")
    self.step4_registrationLabel.wordWrap = True
    self.step4_registrationCollapsibleButtonLayout.addWidget(self.step4_registrationLabel)

    # Add empty row
    self.step4_registrationCollapsibleButtonLayout.addWidget(qt.QLabel(''))

    # Perform registration button
    self.step4_performRegistrationButton = qt.QPushButton("Perform registration")
    self.step4_performRegistrationButton.toolTip = "Registers dose volume to the experimental output \n "
    self.step4_registrationCollapsibleButtonLayout.addWidget(self.step4_performRegistrationButton)
    
    # Add empty row
    self.step4_registrationCollapsibleButtonLayout.addWidget(qt.QLabel(''))

    # Connections 
    self.step4_performRegistrationButton.connect('clicked()', self.onPerformRegistrationButtonClicked)

  #------------------------------------------------------------------------------
  def setup_Step5_GammaComparison(self):
  # TODO add to collapsible buttons group
    # Step 2: Load data panel
    self.step5_CollapsibleButton.setProperty('collapsedHeight', 4)
    self.step5_CollapsibleButton.text = "5. Gamma comparison"
    self.sliceletPanelLayout.addWidget(self.step5_CollapsibleButton)

    self.step5_CollapsibleButtonLayout = qt.QVBoxLayout(self.step5_CollapsibleButton)
    self.step5_CollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step5_CollapsibleButtonLayout.setSpacing(4)
    self.sliceletPanelLayout.addStretch(1) # TODO this may need to be moved
    
    # TODO follow onGammaDoseComparison in Gel 
    
    
  #
  # -----------------------
  # Event handler functions
  # -----------------------
  #

  #------------------------------------------------------------------------------
  @vtk.calldata_type(vtk.VTK_OBJECT)
  def onNodeAdded(self, caller, event, calldata):
    addedNode = calldata

    # If importing a scene then save the calibration batch that needs to be parsed
    if slicer.mrmlScene.IsImporting() and addedNode.IsA("vtkMRMLSubjectHierarchyNode"):
      nodeLevel = addedNode.GetLevel()
      if nodeLevel == slicer.vtkMRMLSubjectHierarchyConstants.GetSubjectHierarchyLevelFolder():
        self.batchFolderToParse = addedNode

    # When an ROI is added then save it as the ROI to use for calibration
    if addedNode.IsA('vtkMRMLAnnotationROINode'):
      self.logic.lastAddedRoiNode = addedNode

  #------------------------------------------------------------------------------
  def onSceneEndImport(self, caller, event):
    self.parseImportedBatch()

  #------------------------------------------------------------------------------
  def onViewSelect(self, layoutIndex):
    if layoutIndex == 0:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    elif layoutIndex == 1:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
    elif layoutIndex == 2:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
    elif layoutIndex == 3:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutTabbedSliceView)
    elif layoutIndex == 4:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutDual3DView)
    elif layoutIndex == 5:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpQuantitativeView)
    elif layoutIndex == 6:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpQuantitativeView)

  #------------------------------------------------------------------------------
  def onLoadImageFilesButton(self):
    slicer.util.openAddDataDialog()

  #------------------------------------------------------------------------------
  def onDicomLoad(self):
    slicer.modules.dicom.widgetRepresentation()
    slicer.modules.DICOMWidget.enter()

  #------------------------------------------------------------------------------
  # Step 1

  #------------------------------------------------------------------------------
  def setNumberOfCalibrationFilmsInTable(self, numberOfCalibrationFilms):
    if numberOfCalibrationFilms > self.maxNumberOfCalibrationFilms:
      message = 'Maximum number of calibration films supported: ' + str(self.maxNumberOfCalibrationFilms) + ', requested: ' + str(numberOfCalibrationFilms)
      qt.QMessageBox.critical(None, 'Empty directory must be chosen', message)
      logging.error(message)
      return

    for row in xrange(numberOfCalibrationFilms):
      self.step1_calibrationVolumeSelectorLabelBeforeList[row].visible = True
      self.step1_calibrationVolumeSelectorCGySpinBoxList[row].visible = True
      self.step1_calibrationVolumeSelectorCGyLabelList[row].visible = True
      self.step1_calibrationVolumeSelectorComboBoxList[row].visible = True

    for row in xrange(numberOfCalibrationFilms, self.maxNumberOfCalibrationFilms):
      self.step1_calibrationVolumeSelectorLabelBeforeList[row].visible = False
      self.step1_calibrationVolumeSelectorCGySpinBoxList[row].visible = False
      self.step1_calibrationVolumeSelectorCGyLabelList[row].visible = False
      self.step1_calibrationVolumeSelectorComboBoxList[row].visible = False

  #------------------------------------------------------------------------------
  def onNumberOfCalibrationFilmsSpinBoxValueChanged(self):
    self.setNumberOfCalibrationFilmsInTable(self.step1_numberOfCalibrationFilmsSpinBox.value)

  #------------------------------------------------------------------------------
  def collectCalibrationFilms(self):
    calibrationDoseToVolumeNodeMap = {}
    for currentCalibrationVolumeIndex in xrange(self.step1_numberOfCalibrationFilmsSpinBox.value):
      currentCalibrationVolumeNode = self.step1_calibrationVolumeSelectorComboBoxList[currentCalibrationVolumeIndex].currentNode()
      currentCalibrationDose = self.step1_calibrationVolumeSelectorCGySpinBoxList[currentCalibrationVolumeIndex].value
      calibrationDoseToVolumeNodeMap[currentCalibrationDose] = currentCalibrationVolumeNode
    return calibrationDoseToVolumeNodeMap

  #------------------------------------------------------------------------------
  def onSaveCalibrationBatchButton(self):
    # Show folder selector window
    calibrationBatchDirectoryPath = qt.QFileDialog.getExistingDirectory(0, 'Select directory to save calibration batch')

    # Get flood field image node
    floodFieldImageVolumeNode = self.step1_floodFieldImageSelectorComboBox.currentNode()
    # Collect calibration doses and volumes
    calibrationDoseToVolumeNodeMap = self.collectCalibrationFilms()

    # Save calibration batch
    message = self.logic.saveCalibrationBatch(calibrationBatchDirectoryPath, floodFieldImageVolumeNode, calibrationDoseToVolumeNodeMap)
    if message != "":
      qt.QMessageBox.critical(None, 'Error when saving calibration batch', message)
      logging.error(message)
    else:
      qt.QMessageBox.information(None, "Calibration batch saving" , "Calibration batch successfully saved")

  #------------------------------------------------------------------------------
  def onLoadCalibrationBatchButton(self):
    # Show folder selector window
    calibrationBatchDirectoryPath = qt.QFileDialog.getExistingDirectory(0, 'Open directory containing calibration batch')

    mrmlFilesFound = 0
    calibrationBatchMrmlSceneFileName = None
    os.chdir(os.path.normpath(calibrationBatchDirectoryPath))
    for potentialMrmlFileName in glob.glob("*.mrml"):
      mrmlFilesFound += 1
      calibrationBatchMrmlSceneFileName = potentialMrmlFileName

    if mrmlFilesFound > 1:
      qt.QMessageBox.critical(None, 'Error when loading calibration batch', "More than one MRML file found in directory!\n\nThe calibration batch directory must contain exactly one MRML file")
      logging.error("More than one MRML files found in directory " + calibrationBatchDirectoryPath)
      return
    elif mrmlFilesFound < 1:
      qt.QMessageBox.critical(None, 'Error when loading calibration batch', "No MRML file found in directory!\n\nThe calibration batch directory must contain exactly one MRML file")
      logging.error("No MRML file found in directory " + calibrationBatchDirectoryPath)
      return

    # Show wait cursor while loading
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

    calibrationBatchMrmlSceneFilePath = os.path.normpath(calibrationBatchDirectoryPath + "/" + calibrationBatchMrmlSceneFileName)
    success = slicer.util.loadScene(calibrationBatchMrmlSceneFilePath)

    # Restore cursor
    qt.QApplication.restoreOverrideCursor()

  #------------------------------------------------------------------------------
  def parseImportedBatch(self):
    if self.batchFolderToParse is None:
      message = "Invalid saved directory, no subject hierarchy folder is selected to parse!"
      qt.QMessageBox.critical(None, 'Error when loading calibration batch', message)
      logging.error(message)
      return message

    currentCalibrationFilmIndex = 0
    loadedFloodFieldScalarVolume = None
    lastLoadedCalibrationVolume = None

    # Inspect nodes under batch folder node and assign them to roles and dose levels
    slicer.mrmlScene.InitTraversal()
    currentShNode = slicer.mrmlScene.GetNextNodeByClass("vtkMRMLSubjectHierarchyNode")
    while currentShNode:
      if currentShNode.GetParentNode() != self.batchFolderToParse:
        # Skip if not under batch folder node
        currentShNode = slicer.mrmlScene.GetNextNodeByClass("vtkMRMLSubjectHierarchyNode")
        continue

      # Flood film image
      if currentShNode.GetAttribute(self.logic.calibrationVolumeDoseAttributeName) == self.logic.floodFieldAttributeValue:
        if loadedFloodFieldScalarVolume is None:
          loadedFloodFieldScalarVolume = currentShNode.GetAssociatedNode()
          self.step1_floodFieldImageSelectorComboBox.setCurrentNode(loadedFloodFieldScalarVolume)
        else:
          message = "More than one flood field image found"
          qt.QMessageBox.critical(None, 'Error', message)
          logging.error(message)
          slicer.mrmlScene.Clear(0)
          return message
      # Calibration film
      else:
        try:
          # Set dose level
          doseLevel_cGy = int( currentShNode.GetAttribute(self.logic.calibrationVolumeDoseAttributeName) )
          self.step1_calibrationVolumeSelectorCGySpinBoxList[currentCalibrationFilmIndex].value = doseLevel_cGy

          # Set calibration film for dose level
          loadedCalibrationVolume = currentShNode.GetAssociatedNode()
          self.step1_calibrationVolumeSelectorComboBoxList[currentCalibrationFilmIndex].setCurrentNode(loadedCalibrationVolume)

          lastLoadedCalibrationVolume = loadedCalibrationVolume
          currentCalibrationFilmIndex += 1
        except ValueError:
          logging.warning('Invalid calibration film dose attribute "' + repr(currentShNode.GetAttribute(self.logic.calibrationVolumeDoseAttributeName)) + '" in inspected node named' + currentShNode.GetName())

      currentShNode = slicer.mrmlScene.GetNextNodeByClass("vtkMRMLSubjectHierarchyNode")

    # Update calibration films table to set row visibilities
    self.step1_numberOfCalibrationFilmsSpinBox.value = currentCalibrationFilmIndex

    # Reset saved folder node
    self.batchFolderToParse = None

    if loadedFloodFieldScalarVolume is None:
      message = 'Failed to find flood field image!'
      qt.QMessageBox.critical(None, 'Error during parsing batch', message)
      logging.error(message)

    # Show last loaded film
    if lastLoadedCalibrationVolume is not None:
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      selectionNode.SetActiveVolumeID(lastLoadedCalibrationVolume.GetID())
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()
    else:
      message = 'Failed to find any calibration film image!'
      qt.QMessageBox.critical(None, 'Error during parsing batch', message)
      logging.error(message)

    return ""

  #------------------------------------------------------------------------------
  def onAddRoiButton(self):
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    interactionNode = appLogic.GetInteractionNode()

    # Switch to ROI place mode
    selectionNode.SetReferenceActivePlaceNodeClassName('vtkMRMLAnnotationROINode')
    interactionNode.SwitchToSinglePlaceMode()

  #------------------------------------------------------------------------------
  # Step 2

  #------------------------------------------------------------------------------
  def onExperimentalFilmSpacingChanged(self):
    try:
      self.logic.experimentalFilmPixelSpacing = float(self.step2_experimentalFilmSpacingLineEdit.text)
    except ValueError:
      return
  #------------------------------------------------------------------------------
  def onStep2_loadExperimentalDataCollapsed(self, collapsed):
    if collapsed:
      # Save experimental data selection
      self.saveExperimentalDataSelection()

      # Set auto window/level for dose volume
      self.logic.setAutoWindowLevelToAllDoseVolumes()

  #------------------------------------------------------------------------------
  def saveExperimentalDataSelection(self):
    self.logic.experimentalFloodFieldImageNode = self.step2_floodFieldImageSelectorComboBox.currentNode()
    self.logic.experimentalFilmImageNode = self.step2_experimentalFilmSelectorComboBox.currentNode()
    self.logic.planDoseVolumeNode = self.step2_planDoseVolumeSelector.currentNode()

  #------------------------------------------------------------------------------
  # Step 3

  #------------------------------------------------------------------------------
  def onStep3_ApplyCalibrationCollapsed(self, collapsed):
    if not collapsed:
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      if self.logic.experimentalFilmImageNode is not None:
        selectionNode.SetActiveVolumeID(self.logic.experimentalFilmImageNode.GetID())
      else:
        selectionNode.SetActiveVolumeID(None)
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()

  #------------------------------------------------------------------------------
  def onPerformCalibrationButton(self):
    # Get flood field image node
    floodFieldImageVolumeNode = self.step1_floodFieldImageSelectorComboBox.currentNode()
    # Collect calibration doses and volumes
    calibrationDoseToVolumeNodeMap = self.collectCalibrationFilms()

    # Show wait cursor while processing
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

    # Perform calibration
    message = self.logic.performCalibration(floodFieldImageVolumeNode, calibrationDoseToVolumeNodeMap)
    if message != "":
      qt.QMessageBox.critical(None, 'Error when performing calibration', message)
      logging.error(message)

    # Restore cursor
    qt.QApplication.restoreOverrideCursor()

    # Show calibration plot
    self.createCalibrationCurvesWindow()
    self.showCalibrationCurves()

    # Fill calibration entry line edits (so that the rounded values are not written back to the member variable storing the coefficients)
    aText = str(round(self.logic.calibrationCoefficients[0],5))
    bText = str(round(self.logic.calibrationCoefficients[1],5))
    cText = str(round(self.logic.calibrationCoefficients[2],5))
    nText = str(round(self.logic.calibrationCoefficients[3],5))
    self.step3_calibrationFunctionOrder0LineEdit.blockSignals(True)
    self.step3_calibrationFunctionOrder0LineEdit.text = aText
    self.step3_calibrationFunctionOrder0LineEdit.blockSignals(False)
    self.step3_calibrationFunctionOrder1LineEdit.blockSignals(True)
    self.step3_calibrationFunctionOrder1LineEdit.text = bText
    self.step3_calibrationFunctionOrder1LineEdit.blockSignals(False)
    self.step3_calibrationFunctionOrder2LineEdit.blockSignals(True)
    self.step3_calibrationFunctionOrder2LineEdit.text = cText
    self.step3_calibrationFunctionOrder2LineEdit.blockSignals(False)
    self.step3_calibrationFunctionExponentLineEdit.blockSignals(True)
    self.step3_calibrationFunctionExponentLineEdit.text = nText
    self.step3_calibrationFunctionExponentLineEdit.blockSignals(False)

    # Calibration function label
    self.step1_2_performCalibrationFunctionLabel.text = "Dose (cGy) = " + aText + " + " + bText + " * OD + " + cText + " * OD^" + nText

  #------------------------------------------------------------------------------
  def onCalibrationFunctionLineEditChanged(self):
    if self.step3_calibrationFunctionOrder0LineEdit.text != '':
      try:
        self.logic.calibrationCoefficients[0] = float(self.step3_calibrationFunctionOrder0LineEdit.text)
      except ValueError:
        logging.error("Invalid numeric value for calibration function coefficient 'A' " + self.step3_calibrationFunctionOrder0LineEdit.text)
    if self.step3_calibrationFunctionOrder1LineEdit.text != '':
      try:
        self.logic.calibrationCoefficients[1] = float(self.step3_calibrationFunctionOrder1LineEdit.text)
      except ValueError:
        logging.error("Invalid numeric value for calibration function coefficient 'B' " + self.step3_calibrationFunctionOrder1LineEdit.text)
    if self.step3_calibrationFunctionOrder2LineEdit.text != '':
      try:
        self.logic.calibrationCoefficients[2] = float(self.step3_calibrationFunctionOrder2LineEdit.text)
      except ValueError:
        logging.error("Invalid numeric value for calibration function coefficient 'C' " + self.step3_calibrationFunctionOrder2LineEdit.text)
    if self.step3_calibrationFunctionExponentLineEdit.text != '':
      try:
        self.logic.calibrationCoefficients[3] = float(self.step3_calibrationFunctionExponentLineEdit.text)
      except ValueError:
        logging.error("Invalid numeric value for calibration function coefficient 'N' " + self.step3_calibrationFunctionExponentLineEdit.text)

  #------------------------------------------------------------------------------
  def fitOpticalDensityFunction(self, doseVSOpticalDensityNestedList): #TODO: Unused function!
    x = [ODEntry[0] for ODEntry in doseVSOpticalDensityNestedList]
    y = [ODEntry[1] for ODEntry in doseVSOpticalDensityNestedList]
    self.opticalDensityCurve = numpy.polyfit(x,y,3)
    opticalDensityToDosePolynomialFunction = numpy.poly1d(self.opticalDensityCurve)
    return opticalDensityToDosePolynomialFunction

  #------------------------------------------------------------------------------
  def createCalibrationCurvesWindow(self):
    # Set up window to be used for displaying data
    self.calibrationCurveChartView = vtk.vtkContextView()
    self.calibrationCurveChartView.GetRenderer().SetBackground(1,1,1)
    self.calibrationCurveChart = vtk.vtkChartXY()
    self.calibrationCurveChartView.GetScene().AddItem(self.calibrationCurveChart)

  #------------------------------------------------------------------------------
  def showCalibrationCurves(self):
    # Create CALIBRATION dose vs. optical density plot
    self.calibrationCurveDataTable = vtk.vtkTable()
    calibrationNumberOfRows = len(self.logic.measuredOpticalDensityToDoseMap)

    opticalDensityArray = vtk.vtkDoubleArray()
    opticalDensityArray.SetName("Optical Density")
    self.calibrationCurveDataTable.AddColumn(opticalDensityArray)
    dose_cGyCalibrationCurveArray = vtk.vtkDoubleArray()
    dose_cGyCalibrationCurveArray.SetName("Dose (cGy)")
    self.calibrationCurveDataTable.AddColumn(dose_cGyCalibrationCurveArray)
    self.calibrationCurveDataTable.SetNumberOfRows(calibrationNumberOfRows)

    for rowIndex in xrange(calibrationNumberOfRows):
      self.calibrationCurveDataTable.SetValue(rowIndex, 0, self.logic.measuredOpticalDensityToDoseMap[rowIndex][0])
      self.calibrationCurveDataTable.SetValue(rowIndex, 1, self.logic.measuredOpticalDensityToDoseMap[rowIndex][1])

    if hasattr(self, 'calibrationMeanOpticalAttenuationLine' ):
      self.calibrationCurveChart.RemovePlotInstance(self.calibrationMeanOpticalAttenuationLine)
    self.calibrationMeanOpticalAttenuationLine = self.calibrationCurveChart.AddPlot(vtk.vtkChart.POINTS)
    self.calibrationMeanOpticalAttenuationLine.SetInputData(self.calibrationCurveDataTable, 0, 1)
    self.calibrationMeanOpticalAttenuationLine.SetColor(0, 0, 255, 255)
    self.calibrationMeanOpticalAttenuationLine.SetWidth(2.0)

    # Create and populate the calculated dose/OD curve with function
    opticalDensityList = [round(0 + 0.01*opticalDensityIncrement,2) for opticalDensityIncrement in xrange(120)] #TODO: Magic number 120? Rounding?
    opticalDensities = []

    for calculatedEntryIndex in xrange(120):
      newEntry = [opticalDensityList[calculatedEntryIndex], self.logic.applyCalibrationFunctionOnSingleOpticalDensityValue(opticalDensityList[calculatedEntryIndex], self.logic.calibrationCoefficients[0], self.logic.calibrationCoefficients[1], self.logic.calibrationCoefficients[2], self.logic.calibrationCoefficients[3])]
      opticalDensities.append(newEntry)

    # Create plot for dose calibration fitted curve
    self.opticalDensityToDoseFunctionTable = vtk.vtkTable()
    opticalDensityNumberOfRows = len(opticalDensities)
    opticalDensityCalculatedArray = vtk.vtkDoubleArray()
    opticalDensityCalculatedArray.SetName("opticalDensities")
    self.opticalDensityToDoseFunctionTable.AddColumn(opticalDensityCalculatedArray)
    dose_cGyCalculatedArray = vtk.vtkDoubleArray()
    dose_cGyCalculatedArray.SetName("Optical Density")
    self.opticalDensityToDoseFunctionTable.AddColumn(dose_cGyCalculatedArray)

    self.opticalDensityToDoseFunctionTable.SetNumberOfRows(opticalDensityNumberOfRows)
    for opticalDensityIncrement in xrange(opticalDensityNumberOfRows):
      self.opticalDensityToDoseFunctionTable.SetValue(opticalDensityIncrement, 0, opticalDensities[opticalDensityIncrement][0])
      self.opticalDensityToDoseFunctionTable.SetValue(opticalDensityIncrement, 1, opticalDensities[opticalDensityIncrement][1])

    if hasattr(self, 'calculatedDoseLine'):
      self.calibrationCurveChart.RemovePlotInstance(self.calculatedDoseLine)
    self.calculatedDoseLine = self.calibrationCurveChart.AddPlot(vtk.vtkChart.LINE)
    self.calculatedDoseLine.SetInputData(self.opticalDensityToDoseFunctionTable, 0, 1)
    self.calculatedDoseLine.SetColor(255, 0, 0, 255)
    self.calculatedDoseLine.SetWidth(2.0)

    # Show chart
    self.calibrationCurveChart.GetAxis(1).SetTitle('Optical Density')
    self.calibrationCurveChart.GetAxis(0).SetTitle('Dose (cGy)')
    self.calibrationCurveChart.SetShowLegend(True)
    self.calibrationCurveChart.SetTitle('Dose (cGy) vs. Optical Density')
    self.calibrationCurveChartView.GetInteractor().Initialize()
    self.renderWindow = self.calibrationCurveChartView.GetRenderWindow()
    self.renderWindow.SetSize(800,550)
    self.renderWindow.SetWindowName('Dose (cGy) vs. Optical Density')
    self.renderWindow.Start()

  #------------------------------------------------------------------------------
  def onSaveCalibrationFunctionToFileButton(self):
    outputDir = qt.QFileDialog.getExistingDirectory(0, 'Select directory for saving calibration results')

    self.logic.saveCalibrationFunctionToFile(outputDir)

  #------------------------------------------------------------------------------
  def onLoadCalibrationFunctionFromFileButton(self):
    filePath = qt.QFileDialog.getOpenFileName(0, 'Open file')

    self.loadCalibrationFunctionFromFile(filePath)

  #------------------------------------------------------------------------------
  def loadCalibrationFunctionFromFile(self, filePath):
    self.logic.loadCalibrationFunctionFromFile(filePath)

    # Display coefficients (rounded to five digits, but the member variable has full accuracy)
    aText = str(round(self.logic.calibrationCoefficients[0],5))
    bText = str(round(self.logic.calibrationCoefficients[1],5))
    cText = str(round(self.logic.calibrationCoefficients[2],5))
    nText = str(round(self.logic.calibrationCoefficients[3],5))
    self.step3_calibrationFunctionOrder0LineEdit.blockSignals(True)
    self.step3_calibrationFunctionOrder0LineEdit.text = aText
    self.step3_calibrationFunctionOrder0LineEdit.blockSignals(False)
    self.step3_calibrationFunctionOrder1LineEdit.blockSignals(True)
    self.step3_calibrationFunctionOrder1LineEdit.text = bText
    self.step3_calibrationFunctionOrder1LineEdit.blockSignals(False)
    self.step3_calibrationFunctionOrder2LineEdit.blockSignals(True)
    self.step3_calibrationFunctionOrder2LineEdit.text = cText
    self.step3_calibrationFunctionOrder2LineEdit.blockSignals(False)
    self.step3_calibrationFunctionExponentLineEdit.blockSignals(True)
    self.step3_calibrationFunctionExponentLineEdit.text = nText
    self.step3_calibrationFunctionExponentLineEdit.blockSignals(False)

  #------------------------------------------------------------------------------
  def onApplyCalibrationButton(self):
    # Show wait cursor while processing
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

    # Apply calibration function on experimental image
    message = self.logic.applyCalibrationOnExperimentalFilm()
    if message != "":
      qt.QMessageBox.critical(None, 'Error when applying calibration', message)
      logging.error(message)

    # Restore cursor
    qt.QApplication.restoreOverrideCursor()

    qt.QMessageBox.information(None, "Calibration" , "Calibration successfully finished!")

  #------------------------------------------------------------------------------
  # Step 4

  #------------------------------------------------------------------------------
  def onPerformRegistrationButtonClicked(self): #TODO:
    # TODO merge step 2 and step 4

    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

    # Perform registration
    message = self.logic.registerExperimentalFilmToPlanDose()
    if message != "":
      qt.QMessageBox.critical(None, 'Error when performing calibration', message)
      logging.error(message)

    qt.QApplication.restoreOverrideCursor()

    # Show registered images
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(self.logic.paddedCalibratedExperimentalFilmVolumeNode.GetID())
    selectionNode.SetSecondaryVolumeID(self.logic.paddedPlanDoseSliceVolumeNode.GetID())
    appLogic.PropagateVolumeSelection()

  #------------------------------------------------------------------------------
  # Step 5


  #
  # -------------------------
  # Testing related functions
  # -------------------------
  #
  def onSelfTestButtonClicked(self):
    # Test data
    calibrationBatchMrmlSceneFilePath = "d:/images/RT/20160624_FilmDosimetry_TestDataset/Batch/20160804_221203__CalibrationBatchScene.mrml"
    experimentalFilmFilePath = 'd:/images/RT/20160624_FilmDosimetry_TestDataset/20160624_FSRTFilms/experiment.png'
    experimentalFilmSpacing = 0.426
    planDoseVolumeFilePath = "d:/images/RT/20160624_FilmDosimetry_TestDataset/RD.PYPHANTOMTEST_.dcm"
    floodFieldImageNodeName = 'blank'
    experimentalFilmNodeName = 'experiment'
    planDoseVolumeNodeName = '184: RTDOSE: Eclipse Doses: 4PTVs:3-6mm2'
    calibrationFunctionFilePath = "d:/images/RT/20160624_FilmDosimetry_TestDataset/20160804_231433_FilmDosimetryCalibrationFunctionCoefficients.txt"

    # Step 1
    #
    # Load calibration batch
    success = slicer.util.loadScene(calibrationBatchMrmlSceneFilePath)

    #TODO: Test perform calibration too
    
    # Step 2
    #
    # Load experimental film and set spacing
    slicer.util.loadVolume(experimentalFilmFilePath)
    self.step2_experimentalFilmSpacingLineEdit.text = experimentalFilmSpacing

    # Load pan dose from DICOM
    dicomRtPluginInstance = slicer.modules.dicomPlugins['DicomRtImportExportPlugin']()
    loadables = dicomRtPluginInstance.examineForImport([[planDoseVolumeFilePath]])
    dicomRtPluginInstance.load(loadables[0])
    self.logic.setAutoWindowLevelToAllDoseVolumes()
    
    # Assign roles
    self.step2_floodFieldImageSelectorComboBox.setCurrentNode(slicer.util.getNode(floodFieldImageNodeName))
    self.step2_experimentalFilmSelectorComboBox.setCurrentNode(slicer.util.getNode(experimentalFilmNodeName))
    self.step2_planDoseVolumeSelector.setCurrentNode(slicer.util.getNode(planDoseVolumeNodeName))
    
    self.saveExperimentalDataSelection()

    # Step 3
    #
    # Load calibration from file
    self.loadCalibrationFunctionFromFile(calibrationFunctionFilePath)
    
    # Apply calibration
    self.logic.applyCalibrationOnExperimentalFilm()

    # Step 4
    #
    # Perform registration
    self.logic.registerExperimentalFilmToPlanDose()

    # Show registered images
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(self.logic.paddedCalibratedExperimentalFilmVolumeNode.GetID())
    selectionNode.SetSecondaryVolumeID(self.logic.paddedPlanDoseSliceVolumeNode.GetID())
    appLogic.PropagateVolumeSelection()

#
# FilmDosimetryAnalysis
#
class FilmDosimetryAnalysis(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    parent.title = "Film Dosimetry Analysis"
    parent.categories = ["Slicelets"]
    parent.dependencies = ["DicomRtImportExport", "BRAINSFit", "CropVolume", "ResampleScalarVolume", "Annotations", "DataProbe", "DoseComparison"]
    parent.contributors = ["Csaba Pinter (Queen's University), Kevin Alexander (KGH, Queen's University), Alec Robinson (Queen's University)"] # replace with "Firstname Lastname (Org)"
    parent.helpText = "Slicelet for film dosimetry analysis"
    parent.acknowledgementText = """
    This file was originally developed by Kevin Alexander (KGH, Queen's University), Csaba Pinter (Queen's University), and Alec Robinson (Queen's University). Funding was provided by CIHR
    """
    iconPath = os.path.join(os.path.dirname(self.parent.path), 'Resources/Icons', self.moduleName+'.png')
    parent.icon = qt.QIcon(iconPath)


#
# FilmDosimetryAnalysisWidget
#
class FilmDosimetryAnalysisWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)
    slicer.test = self

    # Show slicelet button
    launchSliceletButton = qt.QPushButton("Show slicelet")
    launchSliceletButton.toolTip = "Launch the slicelet"
    self.layout.addWidget(qt.QLabel(' '))
    self.layout.addWidget(launchSliceletButton)
    launchSliceletButton.connect('clicked()', self.onShowSliceletButtonClicked)

    # Add vertical spacer
    self.layout.addStretch(1)

  def onShowSliceletButtonClicked(self):
    mainFrame = SliceletMainFrame()
    mainFrame.minimumWidth = 1200
    mainFrame.windowTitle = "Film dosimetry analysis"
    mainFrame.setWindowFlags(qt.Qt.WindowCloseButtonHint | qt.Qt.WindowMaximizeButtonHint | qt.Qt.WindowTitleHint)
    iconPath = os.path.join(os.path.dirname(slicer.modules.filmdosimetryanalysis.path), 'Resources/Icons', self.moduleName+'.png')
    mainFrame.windowIcon = qt.QIcon(iconPath)
    mainFrame.connect('destroyed()', self.onSliceletClosed)

    slicelet = FilmDosimetryAnalysisSlicelet(mainFrame, self.developerMode)
    mainFrame.setSlicelet(slicelet)

    # Make the slicelet reachable from the Slicer python interactor for testing
    slicer.filmDosimetrySliceletInstance = slicelet

  def onSliceletClosed(self):
    logging.debug('Slicelet closed')

# # ---------------------------------------------------------------------------
class FilmDosimetryAnalysisTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()

#
# Main
#
if __name__ == "__main__":
  #TODO: access and parse command line arguments
  #   Example: SlicerRt/src/BatchProcessing
  #   Ideally handle --xml

  import sys
  logging.debug( sys.argv )

  mainFrame = qt.QFrame()
  slicelet = FilmDosimetryAnalysisSlicelet(mainFrame)
