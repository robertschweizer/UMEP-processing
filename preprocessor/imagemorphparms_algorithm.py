# -*- coding: utf-8 -*-

"""
/***************************************************************************
 ProcessingUMEP
                                 A QGIS plugin
 UMEP for processing toolbox
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2020-04-02
        copyright            : (C) 2020 by Fredrik Lindberg
        email                : fredrikl@gvc.gu.se
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

__author__ = 'Fredrik Lindberg'
__date__ = '2020-04-02'
__copyright__ = '(C) 2020 by Fredrik Lindberg'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterString,
                       QgsProcessingParameterBoolean,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterFolderDestination,
                       QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterField,
                       QgsProcessingException,
                       QgsFeature,
                       QgsVectorFileWriter,
                       QgsVectorDataProvider,
                       QgsField)

from qgis.PyQt.QtGui import QIcon
from osgeo import gdal, osr, ogr
from osgeo.gdalconst import *
import os
import numpy as np
import inspect
from pathlib import Path
import sys
from ..util import RoughnessCalcFunctionV2 as rg
from ..util import imageMorphometricParms_v2 as morph
from ..functions import wallalgorithms as wa


class ProcessingImageMorphParmsAlgorithm(QgsProcessingAlgorithm):
    """
    This algorithm is a processing version of Image Morphometric Calculator Point
    """

    INPUT_POLYGONLAYER = 'INPUT_POLYGONLAYER'
    ID_FIELD = 'ID_FIELD'
    SERACH_METHOD = 'SEARCH_METHOD'
    INPUT_DISTANCE = 'INPUT_DISTANCE'
    INPUT_INTERVAL = 'INPUT_INTERVAL'
    INPUT_DSM = 'INPUT_DSM'
    INPUT_DEM = 'INPUT_DEM'
    INPUT_DSMBUILD = 'INPUT_DSMBUILD'
    USE_DSMBUILD = 'USE_DSM_BUILD'
    ROUGH = 'ROUGH'
    FILE_PREFIX = 'FILE_PREFIX'
    OUTPUT_DIR = 'OUTPUT_DIR'
    IGNORE_NODATA = 'IGNORE_NODATA'
    ATTR_TABLE = 'ATTR_TABLE'
    
    
    def initAlgorithm(self, config):
        self.rough = ((self.tr('Rule of thumb'), '0'),
                        (self.tr('Raupach (1994/95)'), '1'),
                        (self.tr('Simplified Bottema (1995)'), '2'),
                        (self.tr('MacDonald et al. (1998)'), '3'),
                        (self.tr('Millward-Hopkins et al. (2011)'), '4'),
                        (self.tr('Kanda et al. (2013)'), '5'))
        self.search = ((self.tr('Throughout the grid extent'), '0'),
                        (self.tr('From grid centroid'), '1'))
        self.addParameter(QgsProcessingParameterFeatureSource(self.INPUT_POLYGONLAYER,
            self.tr('Vector polygon grid'), [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(self.ID_FIELD,
            self.tr('ID field'),'', self.INPUT_POLYGONLAYER, QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterEnum(self.SERACH_METHOD,
            self.tr('Search method'),
            options=[i[0] for i in self.search], defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(self.INPUT_DISTANCE, 
            self.tr('Search distance from grid cell centroid (m)'),
            QgsProcessingParameterNumber.Integer,
            QVariant(200), False, minValue=0))
        self.addParameter(QgsProcessingParameterNumber(self.INPUT_INTERVAL, 
            self.tr('Wind direction search interval (degree)'), 
            QgsProcessingParameterNumber.Double,
            QVariant(5), False, minValue=0.1, maxValue=360.))
        self.addParameter(QgsProcessingParameterBoolean(self.USE_DSMBUILD,
            self.tr("Raster DSM (only 3D building or vegetation objects) exist"), defaultValue=False))
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_DSM,
            self.tr('Raster DSM (3D objects and ground)'), '', True))
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_DEM,
            self.tr('Raster DEM (only ground)'), '', True))
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_DSMBUILD,
            self.tr('Raster DSM (only 3D objects)'), '', True))
        self.addParameter(QgsProcessingParameterEnum(self.ROUGH,
            self.tr('Roughness calculation method'),
            options=[i[0] for i in self.rough], defaultValue=0))
        self.addParameter(QgsProcessingParameterString(self.FILE_PREFIX, 
            self.tr('File prefix')))
        self.addParameter(QgsProcessingParameterBoolean(self.IGNORE_NODATA,
            self.tr("Ignore NoData pixels"), defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(self.ATTR_TABLE,
            self.tr("Add result to polygon grid attribute table"), defaultValue=False))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_DIR, 
            self.tr('Output folder')))

        self.plugin_dir = os.path.dirname(__file__)
        if not (os.path.isdir(self.plugin_dir + '/data')):
            os.mkdir(self.plugin_dir + '/data')
        self.dir_poly = self.plugin_dir + '/data/poly_temp.shp'

    def processAlgorithm(self, parameters, context, feedback):
        # InputParameters 
        inputPolygonlayer = self.parameterAsVectorLayer(parameters, self.INPUT_POLYGONLAYER, context)
        idField = self.parameterAsFields(parameters, self.ID_FIELD, context)
        searchMethod = self.parameterAsString(parameters, self.SERACH_METHOD, context)
        inputDistance = self.parameterAsDouble(parameters, self.INPUT_DISTANCE, context)
        inputInterval = self.parameterAsDouble(parameters, self.INPUT_INTERVAL, context)
        useDsmBuild = self.parameterAsBool(parameters, self.USE_DSMBUILD, context)
        dsmlayer = None
        demlayer = None
        ro = self.parameterAsString(parameters, self.ROUGH, context)
        filePrefix = self.parameterAsString(parameters, self.FILE_PREFIX, context)
        attrTable = self.parameterAsBool(parameters, self.ATTR_TABLE, context)
        ignoreNodata = self.parameterAsBool(parameters, self.IGNORE_NODATA, context)
        outputDir = self.parameterAsString(parameters, self.OUTPUT_DIR, context)

        
        if parameters['OUTPUT_DIR'] == 'TEMPORARY_OUTPUT':
            if not (os.path.isdir(outputDir)):
                os.mkdir(outputDir)

        # r = inputDistance
        
        degree = float(inputInterval)
        pre = filePrefix
        header = ' Wd pai   fai   zH  zHmax   zHstd zd z0  noOfPixels'
        numformat = '%3d %4.3f %4.3f %5.3f %5.3f %5.3f %5.3f %5.3f %5.0f'
        header2 = ' id  pai   fai   zH  zHmax   zHstd  zd  z0  wai'
        numformat2 = '%3d %4.3f %4.3f %5.3f %5.3f %5.3f %5.3f %5.3f %5.3f'
        ret = 0
        imp_point = 0
        imid = int(searchMethod)
        arrmat = np.empty((1, 9))

        # temporary fix for mac, ISSUE #15
        pf = sys.platform
        if pf == 'darwin' or pf == 'linux2' or pf == 'linux':
            if not os.path.exists(outputDir + '/' + pre):
                os.makedirs(outputDir + '/' + pre)

        # poly = inputPolygonlayer
        poly_field = idField
        vlayer = inputPolygonlayer
        prov = vlayer.dataProvider()
        fields = prov.fields()
        idx = vlayer.fields().indexFromName(poly_field[0])
        # dir_poly = self.plugin_dir + '/data/poly_temp.shp'
        nGrids = vlayer.featureCount()
        index = 1
        feedback.setProgressText("Number of grids to analyse: " + str(nGrids))

        # #Calculate Z0m and Zdm depending on the Z0 method
        if int(ro) == 0:
            Roughnessmethod = 'RT'
        elif int(ro) == 1:
            Roughnessmethod = 'Rau'
        elif int(ro) == 2:
            Roughnessmethod = 'Bot'
        elif int(ro) == 3:
            Roughnessmethod = 'Mac'
        elif int(ro) == 4:
            Roughnessmethod = 'Mho'
        else:
            Roughnessmethod = 'Kan'

        for f in vlayer.getFeatures():  # looping through each grid polygon
            feedback.setProgress(int((index * 100) / nGrids))
            if feedback.isCanceled():
                feedback.setProgressText("Calculation cancelled")
                break
            
            index += 1

            attributes = f.attributes()
            geometry = f.geometry()
            feature = QgsFeature()
            feature.setAttributes(attributes)
            feature.setGeometry(geometry)

            if imid == 1:  # use center point
                r = inputDistance
                y = f.geometry().centroid().asPoint().y()
                x = f.geometry().centroid().asPoint().x()
            else:
                r = 0  # Uses as info to separate from IMP point to grid
                writer = QgsVectorFileWriter(self.dir_poly, "CP1250", fields, prov.wkbType(),
                                                prov.crs(), "ESRI shapefile")
                if writer.hasError() != QgsVectorFileWriter.NoError:
                    raise QgsProcessingException("Error when creating shapefile: ", str(writer.hasError()))
                writer.addFeature(feature)
                del writer

            if imid == 1: # from centroid point
                bbox = (x - r, y + r, x + r, y - r)
            else: # from cutline polygon
                VectorDriver = ogr.GetDriverByName("ESRI Shapefile")
                Vector = VectorDriver.Open(self.dir_poly, 0)  #self.dir_poly
                layer = Vector.GetLayer()
                feature = layer.GetFeature(0)
                geom = feature.GetGeometryRef()
                minX, maxX, minY, maxY = geom.GetEnvelope()
                bbox = (minX, maxY, maxX, minY)  # Reorder bbox to use with gdal_translate
                Vector.Destroy()

            if useDsmBuild:  # Only building heights
                dsmlayer = self.parameterAsRasterLayer(parameters, self.INPUT_DSMBUILD, context)
                if dsmlayer is None:
                    raise QgsProcessingException("No valid building DSM raster layer is selected")

                provider = dsmlayer.dataProvider()
                filePath_dsm_build = str(provider.dataSourceUri())

                # added gdal.Warp() for irregular grids
                bigraster = gdal.Open(filePath_dsm_build)
                if imid == 1:
                    gdal.Translate(self.plugin_dir + '/data/clipdsm.tif', bigraster, projWin=bbox)
                else:
                    clip_spec = gdal.WarpOptions(
                        format="GTiff",
                        cutlineDSName=self.dir_poly,
                        cropToCutline=True
                    )
                    gdal.Warp(self.plugin_dir + '/data/clipdsm.tif', bigraster, options=clip_spec)
                bigraster = None

                dataset = gdal.Open(self.plugin_dir + '/data/clipdsm.tif')
                dsm_array = dataset.ReadAsArray().astype(float)
                sizex = dsm_array.shape[0]
                sizey = dsm_array.shape[1]
                dem_array = np.zeros((sizex, sizey))
                ndDEM = -9999

            else:  # Both building ground heights
                dsmlayer = self.parameterAsRasterLayer(parameters, self.INPUT_DSM, context) 
                demlayer = self.parameterAsRasterLayer(parameters, self.INPUT_DEM, context) 

                if dsmlayer is None:
                    raise QgsProcessingException("No valid ground and building DSM raster layer is selected")
                if demlayer is None:
                    raise QgsProcessingException("No valid ground DEM raster layer is selected")

                provider = dsmlayer.dataProvider()
                filePath_dsm = str(provider.dataSourceUri())
                provider = demlayer.dataProvider()
                filePath_dem = str(provider.dataSourceUri())


                # added gdal.Warp() for irregular grids
                bigraster = gdal.Open(filePath_dsm)
                if imid == 1:
                    gdal.Translate(self.plugin_dir + '/data/clipdsm.tif', bigraster, projWin=bbox)
                else:
                    clip_spec = gdal.WarpOptions(
                        format="GTiff",
                        cutlineDSName=self.dir_poly,
                        cropToCutline=True
                    )
                    gdal.Warp(self.plugin_dir + '/data/clipdsm.tif', bigraster, options=clip_spec)
                bigraster = None
                bigraster = gdal.Open(filePath_dem)
                if imid == 1:
                    gdal.Translate(self.plugin_dir + '/data/clipdem.tif', bigraster, projWin=bbox)
                else:
                    clip_spec = gdal.WarpOptions(
                        format="GTiff",
                        cutlineDSName=self.dir_poly,
                        cropToCutline=True
                    )
                    gdal.Warp(self.plugin_dir + '/data/clipdem.tif', bigraster, options=clip_spec)
                bigraster = None

                # # Remove gdalwarp with gdal.Translate
                # bigraster = gdal.Open(filePath_dsm)
                # gdal.Translate(self.plugin_dir + '/data/clipdsm.tif', bigraster, projWin=bbox)
                # bigraster = None
                # bigraster = gdal.Open(filePath_dem)
                # gdal.Translate(self.plugin_dir + '/data/clipdem.tif', bigraster, projWin=bbox)
                # bigraster = None

                dataset = gdal.Open(self.plugin_dir + '/data/clipdsm.tif')
                dsm_array = dataset.ReadAsArray().astype(float)
                dataset2 = gdal.Open(self.plugin_dir + '/data/clipdem.tif')
                dem_array = dataset2.ReadAsArray().astype(float)
                ndDEM = dataset2.GetRasterBand(1).GetNoDataValue()

                if not (dsm_array.shape[0] == dem_array.shape[0]) & (dsm_array.shape[1] == dem_array.shape[1]):
                    raise QgsProcessingException("All grids must be of same extent and resolution")

            # if not sizex == sizey:
                # raise QgsProcessingException('Vector polygon is not squared in this CRS. Reproject or generate new grid based on current CRS.')
            
            geotransform = dataset.GetGeoTransform()
            scale = 1 / geotransform[1]
            nd = dataset.GetRasterBand(1).GetNoDataValue()
            nodata_test = (dsm_array == nd)
            if ignoreNodata:
                if np.sum(dsm_array) == (dsm_array.shape[0] * dsm_array.shape[1] * nd):
                    feedback.setProgressText("Grid " + str(f.attributes()[idx]) + " not calculated. Includes Only NoData Pixels")
                    cal = 0
                else:
                    # dsm_array[dsm_array == nd] = -9999
                    # dem_array[dem_array == nd] = -9999
                    feedback.setProgressText("Grid " + str(f.attributes()[idx]) + " being calculated.")
                    # feedback.setProgressText("Grid " + str(f.attributes()[idx]) + "includes NoData Pixels. Nodata set to mean of whole grid.")
                    cal = 1
            else:
                if nodata_test.any():
                    feedback.setProgressText("Grid " + str(f.attributes()[idx]) + " not calculated. Includes NoData Pixels")
                    cal = 0
                else:
                    cal = 1
                    feedback.setProgressText("Grid " + str(f.attributes()[idx]) + " being calculated.")

            if cal == 1:
                #set nodata to same
                dsm_array[dsm_array == nd] = -9999
                dem_array[dem_array == ndDEM] = -9999
                immorphresult = morph.imagemorphparam_v2(dsm_array, dem_array, scale, imid, degree, feedback, imp_point)

                zH = immorphresult["zH"]
                fai = immorphresult["fai"]
                pai = immorphresult["pai"]
                zMax = immorphresult["zHmax"]
                zSdev = immorphresult["zH_sd"]
                
                zd, z0 = rg.RoughnessCalcMany(Roughnessmethod, zH, fai, pai, zMax, zSdev)

                # save to file
                arr = np.concatenate((immorphresult["deg"], immorphresult["pai"], immorphresult["fai"],
                                    immorphresult["zH"], immorphresult["zHmax"], immorphresult["zH_sd"], zd, z0, immorphresult["test"]), axis=1)
                np.savetxt(outputDir + '/' + pre + '_' + 'IMPGrid_anisotropic_' + str(f.attributes()[idx]) + '.txt', arr,
                            fmt=numformat, delimiter=' ', header=header, comments='')
                del arr

                zHall = immorphresult["zH_all"]
                faiall = immorphresult["fai_all"]
                paiall = immorphresult["pai_all"]
                zMaxall = immorphresult["zHmax_all"]
                zSdevall = immorphresult["zH_sd_all"]
                zdall, z0all = rg.RoughnessCalc(Roughnessmethod, zHall, faiall, paiall, zMaxall, zSdevall)

                # If zd and z0 are lower than open country, set to open country
                if zdall == 0.0:
                    zdall = 0.1
                if z0all == 0.0:
                    z0all = 0.03

                # If pai is larger than 0 and fai is zero, set fai to 0.001. Issue # 164
                if paiall > 0.:
                    if faiall == 0.:
                        faiall = 0.001

                # adding wai area to isotrophic (wall area index)
                total = 100. / (int(dsm_array.shape[0] * dsm_array.shape[1]))

                numPixels = len(dsm_array[np.where(dsm_array != nd)])
                dsmwall = np.copy(dsm_array)
                dsmwall[dsmwall == nd] = 0
                wallarea = np.sum(wa.findwalls(dsmwall, 2., feedback, total))
                gridArea = numPixels * geotransform[1] * geotransform[1] # changed to work for irregular grids
                # gridArea = (abs(bbox[2]-bbox[0]))*(abs(bbox[1]-bbox[3]))
                wai = wallarea / gridArea

                arr2 = np.array([[f.attributes()[idx], immorphresult["pai_all"], immorphresult["fai_all"], immorphresult["zH_all"],
                                    immorphresult["zHmax_all"], immorphresult["zH_sd_all"], zdall, z0all, wai]])

                arrmat = np.vstack([arrmat, arr2])

            dataset = None
            dataset2 = None

        arrmatsave = arrmat[1: arrmat.shape[0], :]
        np.savetxt(outputDir + '/' + pre + '_' + 'IMPGrid_isotropic.txt', arrmatsave,
                    fmt=numformat2, delimiter=' ', header=header2, comments='')

        if attrTable: 
            feedback.setProgressText("Adding result to layer attribute table") 
            self.addattr(vlayer, arrmatsave, header, pre, feedback, idx)

        return {self.OUTPUT_DIR: outputDir}

    def addattr(self, vlayer, matdata, header, pre, feedback, idx):
        current_index_length = len(vlayer.dataProvider().attributeIndexes())
        caps = vlayer.dataProvider().capabilities()

        if caps & QgsVectorDataProvider.AddAttributes:
            line_split = header.split()
            for x in range(1, len(line_split)):
                vlayer.dataProvider().addAttributes([QgsField(pre + '_' + line_split[x], QVariant.Double)])
                vlayer.commitChanges()
                vlayer.updateFields()
            attr_dict = {}
        else:
            raise QgsProcessingException("Vector Layer does not support adding attributes")

        features = vlayer.getFeatures()

        for f in features:
            attr_dict.clear()
            id = f.id()
            wo = np.where(f.attributes()[idx] == matdata[:, 0])
            if wo[0] >= 0:
                for x in range(1, matdata.shape[1]):
                    attr_dict[current_index_length + x - 1] = float(matdata[wo[0], x])
                vlayer.dataProvider().changeAttributeValues({id: attr_dict})
    
    def name(self):
        return 'Urban Morphology: Morphometric Calculator (Grid)'

    def displayName(self):
        return self.tr(self.name())

    def group(self):
        return self.tr(self.groupId())

    def groupId(self):
        return 'Pre-Processor'

    def shortHelpString(self):
        return self.tr('The Morphometric Calculator (Grid) plugin calculates various morphometric parameters based on digital surface models for '
        'separate vector polygons. The polygons should preferable be squares or any other regular shape. To create such a grid, built in functions '
        'in QGIS can be used (see Vector geometry -> Research Tools -> Create Grid in the Processing Toolbox). The morphometric parameters are used to describe the '
        'roughness of a surface and are included in various local and mesoscale climate models (e.g. Grimmond and Oke 1999). They may vary depending '
        'on what angle (wind direction) you are interested in. Thus, this plugin is able to derive the parameters for different directions. '
        'Preferably, a ground and 3D-object DSM and DEM should be used as input data. The 3D objects are usually buildings but can also be 3D '
        'vegetation (i.e. trees and bushes). It is also possible to derive the parameters from a 3D object DSM with no ground heights.\n'
        '-------------\n'
        'Grimmond CSB and Oke TR (1999) Aerodynamic properties of urban areas derived from analysis of surface form. J Appl Meteorol 38: 1262-1292'
        '\n'
        'Full manual available via the <b>Help</b>-button.')


    def helpUrl(self):
        url = "https://umep-docs.readthedocs.io/en/latest/pre-processor/Urban%20Morphology%20Morphometric%20Calculator%20(Grid).html"
        return url

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def icon(self):
        cmd_folder = Path(os.path.split(inspect.getfile(inspect.currentframe()))[0]).parent
        icon = QIcon(str(cmd_folder) + "/icons/ImageMorphIcon.png")
        return icon

    def createInstance(self):
        return ProcessingImageMorphParmsAlgorithm()