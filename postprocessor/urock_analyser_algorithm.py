# -*- coding: utf-8 -*-

"""
/***************************************************************************
 URockAnalyser
                                 A QGIS plugin
 Analyse results of URock plugin
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2022-01-19
        copyright            : (C) 2022 by Jérémy Bernard, University of Gothenburg
        email                : jeremy.bernard@zaclys.net
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

__author__ = 'Jérémy Bernard, University of Gothenburg'
__date__ = '2022-01-19'
__copyright__ = '(C) 2022 by Jérémy Bernard, University of Gothenburg'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterField,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterMatrix,
                       QgsProcessingParameterFolderDestination,
                       QgsProcessingParameterString,
                       QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterBoolean,
                       QgsRasterLayer,
                       QgsVectorLayer,
                       QgsProject,
                       QgsProcessingContext,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterFile,
                       QgsProcessingException)
#from qgis.utils import iface
import os
from pathlib import Path
import struct
from qgis.PyQt.QtGui import QIcon
import inspect
import xarray as xr

from ..functions.URock.H2gisConnection import getJavaDir, setJavaDir, saveJavaDir
from ..functions.URock.urock_analyser_functions import plotSectionalViews


class URockAnalyserAlgorithm(QgsProcessingAlgorithm):
    """
    This is an example algorithm that takes a vector layer and
    creates a new identical one.

    It is meant to be used as an example of how to create your own
    algorithms and explain methods and variables used to do it. An
    algorithm like this will be available in all elements, and there
    is not need for additional work.

    All Processing algorithms should extend the QgsProcessingAlgorithm
    class.
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    # Input variables
    JAVA_PATH = "JAVA_PATH"
    INPUT_LINES = 'INPUT_LINES'
    INPUT_POLYGONS = 'INPUT_POLYGONS'
    ID_FIELD_LINES = "ID_FIELD_LINES"
    ID_FIELD_POLYGONS = "ID_FIELD_POLYGONS"
    INPUT_WIND_FILE = 'INPUT_WIND_FILE'
    IS_STREAM = 'IS_STREAM'
    OUTPUT_DIRECTORY = 'OUTPUT_DIRECTORY'
    SIMULATION_NAME = "SIMULATION_NAME"


    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        
        # Get the plugin directory to save some useful files
        plugin_directory = self.plugin_dir = os.path.dirname(__file__)
        
        # Get the default value of the Java environment path if already exists
        javaDirDefault = getJavaDir(plugin_directory)
        
        if not javaDirDefault:  # Raise an error if could not find a Java installation
            raise QgsProcessingException("No Java installation found")            
        elif ("Program Files (x86)" in javaDirDefault) and (struct.calcsize("P") * 8 != 32):
            # Raise an error if Java is 32 bits but Python 64 bits
            raise QgsProcessingException('Only a 32 bits version of Java has been'+
                                         'found while your Python installation is 64 bits.'+
                                         'Consider installing a 64 bits Java version.')
        else:   # Set a Java dir if not exist and save it into a file in the plugin repository
            setJavaDir(javaDirDefault)
            saveJavaDir(javaPath = javaDirDefault,
                        pluginDirectory = plugin_directory)

        # We add the input vector features source (line layer)
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_LINES,
                self.tr('Input line layer for vertical sectional plot(s)'),
                [QgsProcessing.TypeVectorLine],
                optional = True
            )
        )
        # Booleans to let the user decide the type of plotting (stream or arrows)
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.IS_STREAM,
                self.tr("Plot streams instead of arrows (works only for cubic voxels"),
                defaultValue=False))
        
        self.addParameter(
            QgsProcessingParameterField(
                self.ID_FIELD_LINES,
                self.tr('Lines ID field (used if mutiple lines is present)'),
                None,
                self.INPUT_LINES,
                QgsProcessingParameterField.Numeric,
                optional = True))
        

        
        # We add the input vector features source (polygon layer)
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_POLYGONS,
                self.tr('Input polygons layer for average wind profile'),
                [QgsProcessing.TypeVectorPolygon],
                optional = True
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.ID_FIELD_POLYGONS,
                self.tr('Polygons ID field (used if mutiple polygons is present)'),
                None,
                self.INPUT_POLYGONS,
                QgsProcessingParameterField.Numeric,
                optional = True))
        # We add the input wind speed saved in a NetCDF format
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_WIND_FILE,
                self.tr('Input wind data file (.nc)'),
                extension='nc'))

        # Output directory and file names
        self.addParameter(
            QgsProcessingParameterString(
                self.SIMULATION_NAME,
                self.tr('Name of the simulation used for saving figure(s)'),
                "",
                False,
                True)) 
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIRECTORY,
                self.tr('Directory to save the figure(s)'),
                optional = True))
        
        # Optional parameter
        self.addParameter(
            QgsProcessingParameterString(
                self.JAVA_PATH,
                self.tr('Java environment path (should be set automatically'),
                javaDirDefault,
                False,
                False)) 

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        
        # Get the plugin directory to save some useful files
        plugin_directory = self.plugin_dir = os.path.dirname(__file__)

        # Defines java environmenet variable
        javaEnvVar = self.parameterAsString(parameters, self.JAVA_PATH, context)
                
        # Defines path of the NetCDF file
        inputWindFile = self.parameterAsString(parameters, self.INPUT_WIND_FILE, context)
        
        # Get line layer, id field name and then file directory and crs
        inputLines = self.parameterAsVectorLayer(parameters, self.INPUT_LINES, context)
        idLines = self.parameterAsString(parameters, self.ID_FIELD_LINES, context)
        if inputLines:
            lines_file = str(inputLines.dataProvider().dataSourceUri())
            if lines_file.count("|") > 0:
                lines_file = lines_file.split("|")[0]
            srid_lines = inputLines.crs().authid()[5:]
        else:
            lines_file = ''
            srid_lines = None
        
        # Get polygon layer, id field name and then file directory and crs
        inputPolygons = self.parameterAsVectorLayer(parameters, self.INPUT_POLYGONS, context)
        idPolygons = self.parameterAsString(parameters, self.ID_FIELD_POLYGONS, context)
        if inputPolygons:
            polygons_file = str(inputPolygons.dataProvider().dataSourceUri())
            if polygons_file.count("|") > 0:
                polygons_file = polygons_file.split("|")[0]
            srid_polygons = inputPolygons.crs().authid()[5:]
        else:
            polygons_file = ''
            srid_polygons = None

        if inputLines and inputPolygons:
            if srid_polygons != srid_lines:
                feedback.pushWarning('Coordinate system of input building layer and vegetation layer differ!')
            
        # Defines outputs
        isStream = self.parameterAsBool(parameters, self.IS_STREAM, context)
        simulationName = self.parameterAsString(parameters, self.SIMULATION_NAME, context)
        outputDirectory = self.parameterAsString(parameters, self.OUTPUT_DIRECTORY, context)

        # Creates the output folder if it does not exist
        if not os.path.exists(outputDirectory) and outputDirectory != '':
            if os.path.exists(Path(outputDirectory).parent.absolute()):
                os.mkdir(outputDirectory)
            else:
                raise QgsProcessingException('The output directory does not exist, neither its parent directory')
        
        # Check that conditions are fullfilled for stream calculation
        if isStream:
            horizontal_res = xr.open_dataset(inputWindFile).horizontal_res
            vertical_res = xr.open_dataset(inputWindFile).vertical_res
            if horizontal_res != vertical_res:
                raise QgsProcessingException('For stream plots, your netCDF file should contain cubic voxels')
        
        # Start the analyser
        fig, ax, scale, fig_poly, ax_poly =\
            plotSectionalViews(pluginDirectory = plugin_directory, 
                               inputWindFile = inputWindFile,
                               lines_file = lines_file,
                               srid_lines = srid_lines,
                               idLines = idLines, 
                               polygons_file = polygons_file,
                               srid_polygons = srid_polygons,
                               idPolygons = idPolygons, 
                               isStream = isStream,
                               savePlot = True,
                               outputDirectory = outputDirectory,
                               simulationName = simulationName,
                               feedback = feedback)
        
        # Return the results of the algorithm.
        return {self.OUTPUT_DIRECTORY: outputDirectory}

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'Urban Wind Field: URock analyzer'

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr('Urban Wind Field: URock AnalyZer')

    def group(self):
        """
        Returns the name of the group this algorithm belongs to. This string
        should be localised.
        """
        return self.tr(self.groupId())

    def groupId(self):
        """
        Returns the unique ID of the group this algorithm belongs to. This
        string should be fixed for the algorithm, and must not be localised.
        The group id should be unique within each provider. Group id should
        contain lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'Post-Processor'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def shortHelpString(self):
        return self.tr('The URock Analyser plugin can be used to plot the results '+
                       'obtained using the URock model along the vertical axis.'+
                       ' This plugin is available only from UMEP for processing <UMEPforProcessing>.\n\n'
                       'Rem: The plug-in performance is far from optimum since the '+
                       'NetCDF file is loaded in Java AND in Python. '+
                       'Thus it could take some time if the NetCDF file is large.'
        '\n'
        '---------------\n'
        'Full manual available via the <b>Help</b>-button.')

    def helpUrl(self):
        url = "https://umep-docs.readthedocs.io/en/latest/post_processor/Urban%20Wind%20Fields%20URock%20Analyzer.html"
        return url
    
    def icon(self):
        cmd_folder = Path(os.path.split(inspect.getfile(inspect.currentframe()))[0]).parent
        icon = QIcon(str(cmd_folder) + "/icons/urock.png")
        return icon

    def createInstance(self):
        return URockAnalyserAlgorithm()
