# -*- coding: utf-8 -*-
"""
/***************************************************************************
 DsgTools
                                 A QGIS plugin
 Brazilian Army Cartographic Production Tools
                             -------------------
        begin                : 2018-03-26
        git sha              : $Format:%H$
        copyright            : (C) 2018 by João P. Esperidião - Cartographic Engineer @ Brazilian Army
        email                : esperidiao.joao@eb.mil.br
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

from qgis.core import QgsMessageLog, QgsVectorLayer, QgsGeometry, QgsFeature, QgsWKBTypes, QgsRectangle, \
                      QgsFeatureRequest, QgsExpression
from PyQt4.QtGui import QMessageBox

import binascii, math
from collections import OrderedDict
from DsgTools.ValidationTools.ValidationProcesses.validationProcess import ValidationProcess
from DsgTools.ValidationTools.ValidationProcesses.createNetworkNodesProcess import CreateNetworkNodesProcess, HidrographyFlowParameters
from DsgTools.GeometricTools.DsgGeometryHandler import DsgGeometryHandler

class VerifyNetworkDirectioningProcess(ValidationProcess):
    def __init__(self, postgisDb, iface, instantiating=False):
        """
        Class constructor.
        :param postgisDb: (DsgTools.AbstractDb) postgis database connection.
        :param iface: (QgisInterface) QGIS interface object.
        :param instantiating: (bool) indication of whether class is being instatiated.
        """
        super(VerifyNetworkDirectioningProcess, self).__init__(postgisDb, iface, instantiating)        
        self.processAlias = self.tr('Verify Network Directioning')
        self.canvas = self.iface.mapCanvas()
        self.DsgGeometryHandler = DsgGeometryHandler(iface)
        if not self.instantiating:
            # get an instance of network node creation method class object
            self.createNetworkNodesProcess = CreateNetworkNodesProcess(postgisDb=postgisDb, iface=iface, instantiating=True)
            # get standard node table name as of in the creation method class  
            self.hidNodeLayerName = self.createNetworkNodesProcess.hidNodeLayerName
            # checks whether node table exists and if it is filled
            if not self.abstractDb.checkIfTableExists('validation', self.hidNodeLayerName):
                QMessageBox.warning(self.iface.mainWindow(), self.tr("Warning!"), self.tr('No node table was found into chosen database. (Did you run Create Network Nodes process?)'))
                return
            # adjusting process parameters
            # getting tables with elements (line primitive)
            self.classesWithElemDict = self.abstractDb.getGeomColumnDictV2(withElements=True, excludeValidation = True)
            interfaceDict = dict()
            for key in self.classesWithElemDict:
                cat, lyrName, geom, geomType, tableType = key.split(',')
                interfaceDict[key] = {
                                        self.tr('Category'):cat,
                                        self.tr('Layer Name'):lyrName,
                                        self.tr('Geometry\nColumn'):geom,
                                        self.tr('Geometry\nType'):geomType,
                                        self.tr('Layer\nType'):tableType
                                     }
            self.networkClassesWithElemDict = self.abstractDb.getGeomColumnDictV2(primitiveFilter=['l'], withElements=True, excludeValidation = True)
            networkFlowParameterList = HidrographyFlowParameters(self.networkClassesWithElemDict.keys())
            self.nodeClassesWithElemDict = self.abstractDb.getGeomColumnDictV2(primitiveFilter=['p'], withElements=True, excludeValidation = False)
            nodeFlowParameterList = HidrographyFlowParameters(self.nodeClassesWithElemDict.keys())
            self.sinkClassesWithElemDict = self.nodeClassesWithElemDict
            sinkFlowParameterList = HidrographyFlowParameters(self.sinkClassesWithElemDict.keys())
            self.parameters = {
                                # 'Only Selected' : False,
                                'Network Layer' : networkFlowParameterList,
                                'Node Layer' : nodeFlowParameterList,
                                'Sink Layer' : sinkFlowParameterList,
                                'Reference and Water Body Layers': OrderedDict( {
                                                                       'referenceDictList':{},
                                                                       'layersDictList':interfaceDict
                                                                     } ),
                                'Search Radius' : 5.0,
                                'Max. Directioning Cycles' : 5,
                                'Select All Valid Lines' : False
                              }
            # transmit these parameters to CreateNetworkNodesProcess object
            self.createNetworkNodesProcess.parameters = self.parameters
            # in order to execute attribute check (method on creation process)
            self.createNetworkNodesProcess.networkClassesWithElemDict = self.networkClassesWithElemDict
            self.nodeIdDict = None
            self.nodeDict = None
            self.nodeTypeDict = None
            # retrieving types from node creation object
            self.nodeTypeNameDict = self.createNetworkNodesProcess.nodeTypeNameDict
            self.reclassifyNodeType = dict()
            # list of nodes to be popped from node dict
            self.nodesToPop = []

    def getFirstNode(self, lyr, feat, geomType=None):
        """
        Returns the starting node of a line.
        :param lyr: layer containing target feature.
        :param feat: feature which initial node is requested.
        :param geomType: (int) layer geometry type (1 for lines).
        :return: starting node point (QgsPoint).
        """
        n = self.DsgGeometryHandler.getFeatureNodes(layer=lyr, feature=feat, geomType=geomType)
        isMulti = QgsWKBTypes.isMultiType(int(lyr.wkbType()))
        if isMulti:
            if len(n) > 1:
                return
            return n[0][0]
        elif n:
            return n[0]

    def getSecondNode(self, lyr, feat, geomType=None):
        """
        Returns the second node of a line.
        :param lyr: layer containing target feature.
        :param feat: feature which initial node is requested.
        :param geomType: (int) layer geometry type (1 for lines).
        :return: starting node point (QgsPoint).
        """
        n = self.DsgGeometryHandler.getFeatureNodes(layer=lyr, feature=feat, geomType=geomType)
        isMulti = QgsWKBTypes.isMultiType(int(lyr.wkbType()))
        if isMulti:
            if len(n) > 1:
                # process doesn't treat multipart features that does have more than 1 part
                return
            return n[0][1]
        elif n:
            return n[1]

    def getPenultNode(self, lyr, feat, geomType=None):
        """
        Returns the penult node of a line.
        :param lyr: layer containing target feature.
        :param feat: feature which last node is requested.
        :param geomType: (int) layer geometry type (1 for lines).
        :return: ending node point (QgsPoint).
        """
        n = self.DsgGeometryHandler.getFeatureNodes(layer=lyr, feature=feat, geomType=geomType)
        isMulti = QgsWKBTypes.isMultiType(int(lyr.wkbType()))
        if isMulti:
            if len(n) > 1:
                return
            return n[0][-2]
        elif n:
            return n[-2]

    def getLastNode(self, lyr, feat, geomType=None):
        """
        Returns the ending point of a line.
        :param lyr: (QgsVectorLayer) layer containing target feature.
        :param feat: (QgsFeature) feature which last node is requested.
        :param geomType: (int) layer geometry type (1 for lines).
        :return: ending node point (QgsPoint).
        """
        n = self.DsgGeometryHandler.getFeatureNodes(layer=lyr, feature=feat, geomType=geomType)
        isMulti = QgsWKBTypes.isMultiType(int(lyr.wkbType()))
        if isMulti:
            if len(n) > 1:
                return
            return n[0][-1]
        elif n:
            return n[-1]

    def calculateAngleDifferences(self, startNode, endNode):
        """
        Calculates the angle in degrees formed between line direction ('startNode' -> 'endNode') and vertical passing over 
        starting node.
        :param startNode: node (QgsPoint) reference for line and angle calculation.
        :param endNode: ending node (QgsPoint) for (segment of) line of which angle is required.
        :return: (float) angle in degrees formed between line direction ('startNode' -> 'endNode') and vertical passing over 'startNode'
        """
        # the returned angle is measured regarding 'y-axis', with + counter clockwise and -, clockwise.
        # Then angle is ALWAYS 180 - ang 
        return 180 - math.degrees(math.atan2(endNode.x() - startNode.x(), endNode.y() - startNode.y()))

    def calculateAzimuthFromNode(self, node, networkLayer, geomType=None):
        """
        Computate all azimuths from (closest portion of) lines flowing in and out of a given node.
        :param node: (QgsPoint) hidrography node reference for line and angle calculation.
        :param networkLayer: (QgsVectorLayer) hidrography line layer.
        :param geomType: (int) layer geometry type (1 for lines).
        :return: dict of azimuths of all lines ( { featId : azimuth } )
        """
        if not geomType:
            geomType = networkLayer.geometryType()
        nodePointDict = self.nodeDict[node]
        azimuthDict = dict()
        for line in nodePointDict['start']:
            # if line starts at node, then angle calculate is already azimuth
            endNode = self.getSecondNode(lyr=networkLayer, feat=line, geomType=geomType)
            azimuthDict[line] = node.azimuth(endNode)
        for line in nodePointDict['end']:
            # if line ends at node, angle must be adapted in order to get azimuth
            endNode = self.getPenultNode(lyr=networkLayer, feat=line, geomType=geomType)
            azimuthDict[line] = node.azimuth(endNode)
        return azimuthDict

    def checkLineDirectionConcordance(self, line_a, line_b, networkLayer, geomType=None):
        """
        Given two lines, this method checks whether lines flow to/from the same node or not.
        If they do not have a common node, method returns false.
        :param line_a: (QgsFeature) line to be compared flowing to a common node.
        :param line_b: (QgsFeature) the other line to be compared flowing to a common node.
        :param networkLayer: (QgsVectorLayer) hidrography line layer.
        :return: (bool) True if lines are flowing to/from the same.
        """
        if not geomType:
            geomType = networkLayer.geometryType()
        # first and last node of each line
        fn_a = self.getFirstNode(lyr=networkLayer, feat=line_a, geomType=geomType)
        ln_a = self.getLastNode(lyr=networkLayer, feat=line_a, geomType=geomType)
        fn_b = self.getFirstNode(lyr=networkLayer, feat=line_b, geomType=geomType)
        ln_b = self.getLastNode(lyr=networkLayer, feat=line_b, geomType=geomType)
        # if lines are flowing to/from the same node (they are flowing the same way)
        return (fn_a == fn_b or ln_a == ln_b)

    def validateDeltaLinesAngV2(self, node, networkLayer, connectedValidLines, geomType=None):
        """
        Validates a set of lines connected to a node as for the angle formed between them.
        :param node: (QgsPoint) hidrography node to be validated.
        :param networkLayer: (QgsVectorLayer) hidrography line layer.
        :param connectedValidLines: list of (QgsFeature) lines connected to 'node' that are already verified.
        :param geomType: (int) layer geometry type. If not given, it'll be evaluated OTF.
        :return: (list-of-obj [dict, dict, str]) returns the dict. of valid lines, dict of inval. lines and
                 invalidation reason, if any, respectively.
        """
        val, inval, reason = dict(), dict(), ""
        if not geomType:
            geomType = networkLayer.geometryType()
        azimuthDict = self.calculateAzimuthFromNode(node=node, networkLayer=networkLayer, geomType=None)
        lines = azimuthDict.keys()
        for idx1, key1 in enumerate(lines):
            if idx1 == len(lines):
                # if first comparison element is already the last feature, all differences are already computed
                break
            for idx2, key2 in enumerate(lines):
                if idx1 >= idx2:
                    # in order to calculate only f1 - f2, f1 - f3, f2 - f3 (for 3 features, for instance)
                    continue
                absAzimuthDifference = math.fmod((azimuthDict[key1] - azimuthDict[key2] + 360), 360)
                if absAzimuthDifference > 180:
                    # the lesser angle should always be the one to be analyzed
                    absAzimuthDifference = (360 - absAzimuthDifference)
                if absAzimuthDifference < 90:
                    # if it's a 'beak', lines cannot have opposing directions (e.g. cannot flow to/from the same node)
                    if not self.checkLineDirectionConcordance(line_a=key1, line_b=key2, networkLayer=networkLayer, geomType=geomType):
                        reason = self.tr('Lines id={0} and id={1} have conflicting directions ({2:.2f} deg).').format(key1.id(), key2.id(), absAzimuthDifference)
                        # checks if any of connected lines are already validated by any previous iteration
                        if key1 not in connectedValidLines:
                            inval[key1.id()] = key1
                        if key2 not in connectedValidLines:
                            inval[key2.id()] = key2
                        return val, inval, reason
                elif absAzimuthDifference != 90:
                    # if it's any other disposition, lines can have the same orientation
                    continue
                else:
                    # if lines touch each other at a right angle, then it is impossible to infer waterway direction
                    reason = self.tr('Cannot infer directions for lines {0} and {1} (Right Angle)').format(key1.id(), key2.id())
                    if key1 not in connectedValidLines:
                            inval[key1.id()] = key1
                    if key2 not in connectedValidLines:
                        inval[key2.id()] = key2
                    return val, inval, reason
        if not inval:
            val = {k.id() : k for k in lines}
        return val, inval, reason

    def checkNodeTypeValidity(self, node, connectedValidLines, networkLayer, geomType=None):
        """
        Checks if lines connected to a node have their flows compatible to node type and valid lines
        connected to it.
        :param node: (QgsPoint) node which lines connected to it are going to be verified.
        :param connectedValidLines: list of (QgsFeature) lines connected to 'node' that are already verified.
        :param networkLayer: (QgsVectorLayer) layer that contains the lines of analyzed network.
        :param geomType: (int) layer geometry type. If not given, it'll be evaluated OTF.
        :return: (list-of-obj [dict, dict, str]) returns the dict. of valid lines, dict of inval. lines and
                 invalidation reason, if any, respectively.
        """
        # getting flow permitions based on node type
        # reference is the node (e.g. 'in' = lines  are ENDING at analyzed node)
        flowType = {
                    CreateNetworkNodesProcess.Flag : None, # 0 - Flag (fim de trecho sem 'justificativa espacial')
                    CreateNetworkNodesProcess.Sink : 'in', # 1 - Sumidouro
                    CreateNetworkNodesProcess.WaterwayBegin : 'out', # 2 - Fonte D'Água
                    CreateNetworkNodesProcess.DownHillNode : 'in', # 3 - Interrupção à Jusante
                    CreateNetworkNodesProcess.UpHillNode : 'out', # 4 - Interrupção à Montante
                    CreateNetworkNodesProcess.Confluence : 'in and out', # 5 - Confluência
                    CreateNetworkNodesProcess.Ramification : 'in and out', # 6 - Ramificação
                    CreateNetworkNodesProcess.AttributeChange : 'in and out', # 7 - Mudança de Atributo
                    CreateNetworkNodesProcess.NodeNextToWaterBody : 'in or out', # 8 - Nó próximo a corpo d'água
                    CreateNetworkNodesProcess.AttributeChangeFlag : None, # 9 - Nó de mudança de atributos conectado em linhas que não mudam de atributos
                    CreateNetworkNodesProcess.NodeOverload : None, # 10 - Há igual número de linhas (>1 para cada fluxo) entrando e saindo do nó
                    CreateNetworkNodesProcess.DisconnectedLine : None, # 11 - Nó conectado a uma linha perdida na rede (teria dois inícios de rede)
                    # CreateNetworkNodesProcess.NodeOverload : None # 10 - Mais 
                   }
        # to avoid calculations in expense of memory
        nodeType = self.nodeTypeDict[node]
        # if node is introduced by operator's modification, it won't be saved to the layer
        if node not in self.nodeTypeDict.keys() and not self.unclassifiedNodes:
            self.unclassifiedNodes = True
            QMessageBox.warning(self.iface.mainWindow(), self.tr('Error!'), self.tr('There are unclassified nodes! Node (re)creation process is recommended before this process.'))
            return None, None, None
        flow = flowType[int(nodeType)]
        nodePointDict = self.nodeDict[node]
        # getting all connected lines to node that are not already validated
        linesNotValidated = list( set( nodePointDict['start']  + nodePointDict['end'] ) - set(connectedValidLines) )
        # starting dicts of valid and invalid lines
        validLines, invalidLines = dict(), dict()
        if not flow:
            # flags have all lines flagged
            if nodeType == CreateNetworkNodesProcess.Flag:
                reason = self.tr('Node was flagged upon classification (probably cannot be an ending hidrography node).')
                invalidLines = { line.id() : line for line in linesNotValidated }
            elif nodeType == CreateNetworkNodesProcess.AttributeChangeFlag:
                if nodePointDict['start'] and nodePointDict['end']:
                    # in case manual error is inserted, this would raise an exception
                    line1, line2 = nodePointDict['start'][0], nodePointDict['end'][0]
                    id1, id2 = line1.id(), line2.id()
                    reason = self.tr('Redundant node. Connected lines ({0}, {1}) share the same set of attributes.').format(id1, id2)
                    if line1 in linesNotValidated:
                        il = line1
                    else:
                        il = line2
                    invalidLines[il.id()] = il
                else:
                    # problem is then, reclassified as a flag
                    self.nodeTypeDict[node] = CreateNetworkNodesProcess.Flag
                    # reclassify node type into layer
                    self.reclassifyNodeType[node] = CreateNetworkNodesProcess.Flag
                    reason = self.tr('Node was flagged upon classification (probably cannot be an ending hidrography node).')
            elif nodeType == CreateNetworkNodesProcess.DisconnectedLine:
                # get line connected to node
                lines = nodePointDict['start'] + nodePointDict['end']
                # just in case there's a node wrong manual reclassification so code doesn't raise an error
                ids = [str(line.id()) for line in lines]
                invalidLines = { line.id() : line for line in lines }
                reason = self.tr('Line {0} disconnected from network.').format(", ".join(ids))
            elif nodeType == CreateNetworkNodesProcess.NodeOverload:
                reason = self.tr('Node is overloaded - 4 or more lines are flowing in (>= 2 lines) and out (>= 2 lines).')
                invalidLines = { line.id() : line for line in linesNotValidated }
            return validLines, invalidLines, reason
        if not linesNotValidated:
            # if there are no lines to be validated, method returns None
            return validLines, invalidLines, ''
        # if 'geomType' is not given, it must be evaluated
        if not geomType:
            geomType = networkLayer.geometryType()
        # reason message in case of invalidity
        reason = ''
        for line in linesNotValidated:
            # getting last and initial node from analyzed line
            finalNode = self.getLastNode(lyr=networkLayer, feat=line, geomType=geomType)
            initialNode = self.getFirstNode(lyr=networkLayer, feat=line, geomType=geomType)
            # line ID
            lineID = line.id()
            # comparing extreme nodes to find out if flow is compatible to node type
            if flow == 'in':
                if node == finalNode:
                    if lineID not in validLines.keys():
                        validLines[lineID] = line
                elif lineID not in invalidLines.keys():
                    invalidLines[lineID] = line
                    reason = "".join([reason, self.tr('Line id={0} does not end at a node with IN flow type (node type is {1}). ').format(lineID, nodeType)])
            elif flow == 'out':
                if node == initialNode:
                    if lineID not in validLines.keys():
                        validLines[lineID] = line
                elif lineID not in invalidLines.keys():
                    invalidLines[lineID] = line
                    reason = "".join([reason, self.tr('Line id={0} does not start at a node with OUT flow type (node type is {1}). ')\
                    .format(lineID, self.nodeTypeNameDict[nodeType])])
            elif flow == 'in and out':
                if bool(len(nodePointDict['start'])) != bool(len(nodePointDict['end'])):
                    # if it's an 'in and out' flow and only one of dicts is filled, then there's an inconsistency
                    invalidLines[lineID] = line
                    thisReason = self.tr('Lines are either flowing only in or out of node. Node classification is {0}.')\
                    .format(self.nodeTypeNameDict[nodeType])
                    if thisReason not in reason:
                        reason = "".join([reason, thisReason])
                elif node in [initialNode, finalNode]:
                    if lineID not in validLines:
                        validLines[lineID] = line
                elif lineID not in invalidLines:
                    invalidLines[lineID] = line
                    reason = "".join([reason, self.tr('Line {0} seems to be invalid (unable to point specific reason).').format(lineID)])
            elif flow == 'in or out':
                # these nodes can either be a waterway beginning or end
                # No invalidation reasons were thought at this point...
                if lineID not in validLines:
                    validLines[lineID] = line
        return  validLines, invalidLines, reason

    def checkNodeValidity(self, node, connectedValidLines, networkLayer, geomType=None, deltaLinesCheckList=None):
        """
        Checks whether a node is valid or not.
        :param node: (QgsPoint) node which lines connected to it are going to be verified.
        :param connectedValidLines: list of (QgsFeature) lines connected to 'node' that are already verified.
        :param networkLayer: (QgsVectorLayer) layer that contains the lines of analyzed network.
        :param geomType: (int) layer geometry type. If not given, it'll be evaluated OTF.
        :param deltaLinesCheckList: (list-of-int) node types that must be checked for their connected lines angles.
        :return: (str) if node is invalid, returns the invalidation reason string.
        """
        
        if not deltaLinesCheckList:
            deltaLinesCheckList = [CreateNetworkNodesProcess.Confluence, CreateNetworkNodesProcess.Ramification] # nodes that have an unbalaced number ratio of flow in/out
        # check coherence to node type and waterway flow
        val, inval, reason = self.checkNodeTypeValidity(node=node, connectedValidLines=connectedValidLines,\
                                                    networkLayer=networkLayer, geomType=geomType)
        # checking angle validity
        if self.nodeTypeDict[node] in deltaLinesCheckList:
            # check for connected lines angles coherence
            val2, inval2, reason2 = self.validateDeltaLinesAngV2(node=node, networkLayer=networkLayer, connectedValidLines=connectedValidLines, geomType=geomType)
            # if any invalid line was validated on because of node type, it shall be moved to invalid dict
            if reason2:
                # updates reason
                if reason:
                    reason = "; ".join([reason, reason2])
                else:
                    reason  = reason2
                # remove any validated line in this iteration
                for lineId in inval2:
                    val.pop(lineId, None)
                # insert into invalidated dict
                inval.update(inval2)
        return val, inval, reason

    def getNextNodes(self, node, networkLayer, geomType=None):
        """
        It returns a list of all other nodes for each line connected to target node.
        :param node: (QgsPoint) node based on which next nodes will be gathered from. 
        :param networkLayer: (QgsVectorLayer) hidrography line layer.
        :return: (list-of-QgsPoint) a list of the other node of lines connected to given hidrography node.
        """
        if not geomType:
            geomType = networkLayer.geometryType()
        nextNodes = []
        nodePointDict = self.nodeDict[node]
        for line in nodePointDict['start']:
            # if line starts at target node, the other extremity is a final node
            nextNodes.append(self.getLastNode(lyr=networkLayer, feat=line, geomType=geomType))
        for line in nodePointDict['end']:
            # if line ends at target node, the other extremity is a initial node
            nextNodes.append(self.getFirstNode(lyr=networkLayer, feat=line, geomType=geomType))
        return nextNodes

    def checkForStartConditions(self, node, validLines, networkLayer, nodeLayer, geomType=None):
        """
        Checks if any of next nodes is a contour condition to directioning process.
        :param node: (QgsPoint) node which needs to have its next nodes checked.
        :param validLines: (list-of-QgsFeature) lines that were alredy checked and validated.
        :param networkLayer: (QgsVectorLayer) network lines layer.
        :param nodeLayer: (QgsVectorLayer) network nodes layer.
        :param geomType: (int) network lines layer geometry type code.
        :return:
        """
        # node type granted as right as start conditions
        inContourConditionTypes = [CreateNetworkNodesProcess.DownHillNode, CreateNetworkNodesProcess.Sink]
        outContourConditionTypes = [CreateNetworkNodesProcess.UpHillNode, CreateNetworkNodesProcess.WaterwayBegin]
        if node in inContourConditionTypes + outContourConditionTypes:
            # if node IS a starting condition, method is not necessary
            return False, ''
        nodes = self.getNextNodes(node=node, networkLayer=networkLayer, geomType=geomType)
        # for faster calculation
        nodeTypeDictAlias = self.nodeTypeDict
        nodeDictAlias = self.nodeDict
        # list of flipped features, if any
        flippedLines, flippedLinesIds = [], []
        # dict indicating whether lines may be flipped or not
        nonFlippableDict, flippableDict = dict(), dict()
        # at first, we assume there are no start conditions on next nodes
        hasStartCondition = False
        for nn in nodes:
            # initiate/clear line variable
            line = None
            if nn in nodeTypeDictAlias:
                nodeType = nodeTypeDictAlias[nn]
            else:
                nodeType = self.classifyNode([nn, nodeTypeDictAlias])
                nodeTypeDictAlias[nn] = nodeType
                self.reclassifyNodeType[nn] = nodeType
            if nodeType in inContourConditionTypes:
                # if next node is a confirmed IN-flowing lines, no lines should start on it
                line = nodeDictAlias[nn]['start'][0] if nodeDictAlias[nn]['start'] else None
                hasStartCondition = True
            elif nodeType in outContourConditionTypes:
                # if next node is a confirmed OUT-flowing lines, no lines should end on it
                line = nodeDictAlias[nn]['end'][0] if nodeDictAlias[nn]['end'] else None
                hasStartCondition = True
            if line:
                # if line is given, then flipping it is necessary
                self.flipSingleLine(line=line, layer=networkLayer, geomType=geomType)
                # if a line is flipped it must be changed in self.nodeDict
                self.updateNodeDict(node=node, line=line, networkLayer=networkLayer, geomType=geomType)
                flippedLines.append(line)
                flippedLinesIds.append(str(line.id()))
                # validLines.append(line)
        # for speed-up
        initialNode = lambda x : self.getFirstNode(lyr=networkLayer, feat=x, geomType=geomType)
        lastNode = lambda x : self.getLastNode(lyr=networkLayer, feat=x, geomType=geomType)
        if flippedLines:
            # map is a for-loop in C
            reclassifyNodeAlias = lambda x : nodeLayer.changeAttributeValue(self.nodeIdDict[x], 2, int(self.reclassifyNodeType[x])) \
                                                if self.reclassifyNode(node=x, nodeLayer=nodeLayer) \
                                                else False
            map(reclassifyNodeAlias, map(initialNode, flippedLines) + map(lastNode, flippedLines))
        return hasStartCondition, flippedLinesIds

    def directNetwork(self, networkLayer, nodeLayer, nodeList=None):
        """
        For every node over the frame [or set as a line beginning], checks for network coherence regarding
        to previous node classification and its current direction. Method considers bordering points as 
        correctly classified.
        :param networkLayer: (QgsVectorLayer) hidrography lines layer from which node are created from.
        :param nodeList: a list of target node points (QgsPoint). If not given, all nodeDict will be read.
        :return: (dict) flag dictionary ( { (QgsPoint) node : (str) reason } ), (dict) dictionaries ( { (int)feat_id : (QgsFeature)feat } ) of invalid and valid lines.
        """
        startingNodeTypes = [CreateNetworkNodesProcess.UpHillNode, CreateNetworkNodesProcess.WaterwayBegin] # node types that are over the frame contour and line BEGINNINGS
        deltaLinesCheckList = [CreateNetworkNodesProcess.Confluence, CreateNetworkNodesProcess.Ramification] # nodes that have an unbalaced number ratio of flow in/out
        if not nodeList:
            # 'nodeList' must start with all nodes that are on the frame (assumed to be well directed)
            nodeList = []
            for node in self.nodeTypeDict.keys():
                if self.nodeTypeDict[node] in startingNodeTypes:
                    nodeList.append(node)
            # if no node to start the process is found, process ends here
            if not nodeList:
                return None, None, self.tr("No network starting point was found")
        # to avoid unnecessary calculations
        geomType = networkLayer.geometryType()
        # initiating the list of nodes already checked and the list of nodes to be checked next iteration
        visitedNodes, newNextNodes = [], []
        nodeFlags = dict()
        # starting dict of (in)valid lines to be returned by the end of method
        validLines, invalidLines = dict(), dict()
        # initiate relation of modified features
        flippedLinesIds, mergedLinesString = [], ""
        while nodeList:
            for node in nodeList:
                # first thing to be done: check if there are more than one non-validated line (hence, enough information for a decision)
                if node in self.nodeDict:
                    startLines = self.nodeDict[node]['start']
                    endLines = self.nodeDict[node]['end']
                    if node not in self.nodeTypeDict:
                        # in case node is not classified
                        self.nodeTypeDict[node] = self.classifyNode([node, nodeLayer])
                        self.reclassifyNodeType[node] = self.nodeTypeDict[node]
                else:
                    # ignore node for possible next iterations by adding it to visited nodes
                    visitedNodes.append(node)
                    continue
                nodeLines = startLines + endLines
                validLinesList = validLines.values()
                if len(set(nodeLines) - set(validLinesList)) > 1:
                    hasStartCondition, flippedLines = self.checkForStartConditions(node=node, validLines=validLinesList, networkLayer=networkLayer, nodeLayer=nodeLayer, geomType=geomType)
                    if hasStartCondition:
                        flippedLinesIds += flippedLines
                    else:
                        # if it is not connected to a start condition, check if node has a valid line connected to it
                        if (set(nodeLines) & set(validLinesList)):
                            # if it does and, check if it is a valid node
                            val, inval, reason = self.checkNodeValidity(node=node, connectedValidLines=validLinesList,\
                                                                        networkLayer=networkLayer, deltaLinesCheckList=deltaLinesCheckList, geomType=geomType)
                            # if node has a valid line connected to it and it is valid, then non-validated lines are proven to be in conformity to
                            # start conditions, then they should be validated and node should be set as visited
                            if reason:
                            # if there are more than 1 line not validated yet and no start conditions around it, 
                            # node will neither be checked nor marked as visited
                                continue
                # check coherence to node type and waterway flow
                val, inval, reason = self.checkNodeValidity(node=node, connectedValidLines=validLinesList,\
                                                            networkLayer=networkLayer, deltaLinesCheckList=deltaLinesCheckList, geomType=geomType)
                # nodes to be removed from next nodes
                removeNode = []
                # if a reason is given, then node is invalid (even if there are no invalid lines connected to it).
                if reason:
                    # try to fix node issues
                    # note that val, inval and reason MAY BE MODIFIED - and there is no problem...
                    flippedLinesIds_, mergedLinesString_ = self.fixNodeFlagsNew(node=node, valDict=val, invalidDict=inval, reason=reason, \
                                                                            connectedValidLines=validLinesList, networkLayer=networkLayer, \
                                                                            nodeLayer=nodeLayer, geomType=geomType, deltaLinesCheckList=deltaLinesCheckList)
                    # keep track of all modifications made
                    if flippedLinesIds_:
                        # IDs not registered yet will be added to final list
                        addIds = set(flippedLinesIds_) - set(flippedLinesIds)
                        # IDs that are registered will be removed (flipping a flipped line returns to original state)
                        removeIds = set(flippedLinesIds_) - addIds
                        flippedLinesIds = list( (set(flippedLinesIds) - removeIds) ) + list( addIds  )
                    if mergedLinesString_:
                        if not mergedLinesString:
                            mergedLinesString = mergedLinesString_
                        else:
                            ", ".join([mergedLinesString,  mergedLinesString_])
                    # if node is still invalid, add to nodeFlagList and add/update its reason
                    if reason:
                        nodeFlags[node] = reason
                    # get next nodes connected to invalid lines
                    for line in inval.values():
                        if line in endLines:
                            removeNode.append(self.getFirstNode(lyr=networkLayer, feat=line))
                        else:
                            removeNode.append(self.getLastNode(lyr=networkLayer, feat=line))
                # set node as visited
                if node not in visitedNodes:
                    visitedNodes.append(node)
                # update general dictionaries with final values
                validLines.update(val)
                invalidLines.update(inval)
                # get next iteration nodes
                newNextNodes += self.getNextNodes(node=node, networkLayer=networkLayer, geomType=geomType)
                # remove next nodes connected to invalid lines
                if removeNode:
                    newNextNodes = list( set(newNextNodes) - set(removeNode) )
            # remove nodes that were already visited
            newNextNodes = list( set(newNextNodes) - set(visitedNodes) )
            # if new nodes are detected, repeat for those
            nodeList = newNextNodes
            newNextNodes = []
        # log all features that were merged and/or flipped
        self.logAlteredFeatures(flippedLines=flippedLinesIds, mergedLinesString=mergedLinesString)
        return nodeFlags, invalidLines, validLines
        
    def buildFlagList(self, nodeFlags, tableSchema, tableName, geometryColumn):
        """
        Builds record list from pointList to raise flags.
        :param nodeFlags: (dict) dictionary containing invalid node and its reason ( { (QgsPoint) node : (str) reason } )
        :param tableSchema: (str) name of schema containing hidrography node table.
        :param tableName: (str) name of hidrography node table.
        :param geometryColumn: (str) name of geometric column on table.
        :return: ( list-of- ( (str)feature_identification, (int)feat_id, (str)invalidation_reason, (hex)geometry, (str)geom_column ) ) list of invalidations found.
        """
        recordList = []
        countNodeNotInDb = 0
        for node, reason in nodeFlags.iteritems():
            if node in self.nodeIdDict:
                featid = self.nodeIdDict[node] if self.nodeIdDict[node] is not None else -9999
            else:
                # if node is not previously classified on database, but then motivates a flag, it should appear on Flags list
                featid = -9999
                countNodeNotInDb += 1
            geometry = binascii.hexlify(QgsGeometry.fromMultiPoint([node]).asWkb())
            recordList.append(('{0}.{1}'.format(tableSchema, tableName), featid, reason, geometry, geometryColumn))
        if countNodeNotInDb:
            # in case there are flagged nodes that are not loaded in DB, user is notified
            msg = self.tr('There are {0} flagged nodes that were introduced to network. Node reclassification is indicated.').format(countNodeNotInDb)
            QgsMessageLog.logMessage(msg, "DSG Tools Plugin", QgsMessageLog.CRITICAL)
        return recordList

    # method for automatic fix
    def getReasonType(self, reason):
        """
        Gets the type of reason. 0 indicates non-fixable reason.
        :param reason: (str) reason of node invalidation.
        :return: (int) reason type.
        """
        fixableReasonExcertsDict = {
                                    self.tr("does not end at a node with IN flow type") : 1,
                                    self.tr("does not start at a node with OUT flow type") : 2,
                                    self.tr("have conflicting directions") : 3,
                                    self.tr('Redundant node.') : 4,
                                    self.tr('Node was flagged upon classification') : 5
                                   }
        for r in fixableReasonExcertsDict.keys():
            if r in reason:
                return fixableReasonExcertsDict[r]
        # if reason is not one of the fixables
        return 0

    # method for automatic fix
    def getLineIdFromReason(self, reason, reasonType):
        """
        Extracts line ID from given reason.
        :param reason: (str) reason of node invalidation.
        :param reasonType: (int) invalidation reason type.
        :return: (list-of-str) line ID (int as str).
        """
        if reasonType in [1, 2]:
            # Lines before being built:
            # self.tr('Line id={0} does not end at a node with IN flow type (node type is {1}). ')
            # self.tr('Line id={0} does not start at a node with OUT flow type (node type is {1}). ')
            return [reason.split(self.tr("id="))[1].split(" ")[0]]
        elif reasonType == 3:
            # Line before being built: self.tr('Lines id={0} and id={1} have conflicting directions ({2:.2f} deg).')
            lineId1 = reason.split(self.tr("id="))[1].split(" ")[0]
            lineId2 = reason.split(self.tr("id="))[2].split(" ")[0]
            return [lineId1, lineId2]
        elif reasonType == 4:
            # Line before being built: self.tr('Redundant node. Connected lines ({0}, {1}) share the same set of attributes.')
            lineId1 = reason.split(self.tr(", "))[0].split("(")[1]
            lineId2 = reason.split(self.tr(", "))[1].split(")")[0]
            return [lineId1, lineId2]
        else:
            # all other reasons can't have their ID extracted
            return []

    def flipSingleLine(self, line, layer, geomType=None):
        """
        Flips a given single line.
        :param line: (QgsFeature) line to be flipped.
        :param layer: (QgsVectorLayer) layer containing target feature.
        :param geomType: (int) layer geometry type code.
        """
        self.DsgGeometryHandler.flipFeature(layer=layer, feature=line, geomType=geomType)

    def flipInvalidLine(self, node, networkLayer, validLines, geomType=None):
        """
        Fixes lines connected to nodes flagged as one way flowing node where it cannot be.
        :param node: (QgsPoint) invalid node to have its lines flipped.
        :param networkLayer: (QgsVectorLayer) layer containing target feature.
        :param validLines: (list-of-QgsFeature) list of all validated lines.
        :param geomType: (int) layer geometry type code.
        :return: (QgsFeature) flipped line.
        """
        # get dictionaries for speed-up
        endDict = self.nodeDict[node]['end']
        startDict = self.nodeDict[node]['start']
        amountLines = len(endDict + startDict)
        # it is considered that 
        if endDict:
            # get invalid line connected to node
            invalidLine = list(set(endDict) - set(validLines))
            if invalidLine:
                invalidLine = invalidLine[0]
        else:
            # get invalid line connected to node
            invalidLine = list(set(startDict) - set(validLines))
            if invalidLine:
                invalidLine = invalidLine[0]
        # if no invalid lines are identified, something else is wrong and flipping won't be the solution
        if not invalidLine:
            return None
        # flipping invalid line
        self.flipSingleLine(line=invalidLine, layer=networkLayer)
        return invalidLine

    def fixAttributeChangeFlag(self, node, networkLayer):
        """
        Merges the given 2 lines marked as sharing the same set of attributes.
        :param node: (QgsPoint) flagged node.
        :param networkLayer: (QgsVectorLayer) network lines layer.
        :return: (str) string containing which line was line the other.
        """
        line_a = self.nodeDict[node]['end'][0]
        line_b = self.nodeDict[node]['start'][0]
        # lines have their order changed so that the deleted line is the intial one
        self.DsgGeometryHandler.mergeLines(line_a=line_b, line_b=line_a, layer=networkLayer)
        # the updated feature should be updated into node dict for the NEXT NODE!
        nn = self.getLastNode(lyr=networkLayer, feat=line_b, geomType=1)
        for line in self.nodeDict[nn]['end']:
            if line.id() == line_b.id():
                self.nodeDict[nn]['end'].remove(line)
                self.nodeDict[nn]['end'].append(line_b)
        # remove attribute change flag node (there are no lines connected to it anymore)
        self.nodesToPop.append(node)
        self.createNetworkNodesProcess.nodeDict[nn]['end'] = self.nodeDict[nn]['end']
        return self.tr('{0} to {1}').format(line_a.id(), line_b.id())

    def updateNodeDict(self, node, line, networkLayer, geomType=None):
        """
        Updates node dictionary. Useful when direction of a (set of) line is changed.
        """
        # getting first and last nodes
        first = self.getFirstNode(lyr=networkLayer, feat=line, geomType=geomType)
        last = self.getLastNode(lyr=networkLayer, feat=line, geomType=geomType)
        changed = self.createNetworkNodesProcess.changeLineDict(nodeList=[first, last], line=line)
        # update this nodeDict with the one from createNetworkNodesProcess object
        self.nodeDict[node] = self.createNetworkNodesProcess.nodeDict[node]
        return changed

    def reclassifyNode(self, node, nodeLayer):
        """
        Reclassifies node.
        :param node: (QgsPoint) node to be reclassified.
        :return: (bool) whether point was modified.
        """
        immutableTypes = [CreateNetworkNodesProcess.UpHillNode, CreateNetworkNodesProcess.DownHillNode, CreateNetworkNodesProcess.WaterwayBegin]
        if self.nodeTypeDict[node] in immutableTypes:
            # if node type is immutable, reclassification is not possible
            return False
        # get new type
        newType = self.classifyNode([node, self.nodeTypeDict])
        if self.nodeTypeDict[node] == newType:
            # if new node type is the same as new, method won't do anything
            return False
        # alter it in feature
        self.nodeTypeDict[node] = newType
        id_ = self.nodeIdDict[node]
        self.reclassifyNodeType[node] = newType
        return True

    def fixDeltaFlag(self, node, networkLayer, validLines, reason, reasonType=3, geomType=None):
        """
        Tries to fix nodes flagged because of their delta angles.
        :param node: (QgsPoint) invalid node.
        :param network: (QgsVectorLayer) contains network lines.
        :param validLines: (list-of-QgsFeature) lines already validated.
        :param reason: (str) reason of node invalidation.
        :param reasonType: (int) code for invalidation reason.
        :param geomType: (int) code for the layer that contains the network lines.
        :return: (QgsFeature) line to be flipped. If no line is identified as flippable, None is returned.
        """
        flipCandidates = self.getLineIdFromReason(reason=reason, reasonType=reasonType)
        for line in self.nodeDict[node]['start'] + self.nodeDict[node]['end']:
            lineId = str(line.id())
            if lineId in flipCandidates and line not in validLines:
                # flip line that is exposed in invalidation reason and is not previously validated
                self.flipSingleLine(line=line, layer=networkLayer, geomType=geomType)
                return line
        # if no line attend necessary requirements for flipping
        return None

    def fixNodeFlagsNew(self, node, valDict, invalidDict, reason, connectedValidLines, networkLayer, nodeLayer, geomType=None, deltaLinesCheckList=None):
        """
        Tries to fix issues flagged on node
        """
        # initiate lists of lines that were flipped/merged
        flippedLinesIds, mergedLinesString = [], []
        # support list of flipped lines
        flippedLines = []
        # get reason type
        reasonType = self.getReasonType(reason=reason)
        if not reasonType:
            # if node invalidation reason is not among the fixable ones, method stops here.
            return flippedLinesIds, mergedLinesString
        ## try to fix node issues
        if reasonType in [1, 2]:
            # original message: self.tr('Line {0} does not end at a node with IN flow type (node type is {1}). ')
            # original message: self.tr('Line {0} does not start at a node with OUT flow type (node type is {1}). ')
            # get flipping candidates
            featIdFlipCandidates = self.getLineIdFromReason(reason=reason, reasonType=reasonType)
            for lineId in featIdFlipCandidates:
                line = invalidDict[int(lineId)]
                if line not in connectedValidLines:
                    # only non-valid lines may be modified
                    self.flipSingleLine(line=line, layer=networkLayer, geomType=geomType)
                    flippedLinesIds.append(lineId)
                    flippedLines.append(line)
        elif reasonType == 3:
            # original message: self.tr('Lines {0} and {1} have conflicting directions ({2:.2f} deg).')
            line = self.fixDeltaFlag(node=node, networkLayer=networkLayer, reason=reason, validLines=connectedValidLines, reasonType=reasonType)
            if line:
                # if a line is flipped it must be changed in self.nodeDict
                self.updateNodeDict(node=node, line=line, networkLayer=networkLayer, geomType=geomType)
        elif reasonType == 4:
            # original message: self.tr('Redundant node. Connected lines ({0}, {1}) share the same set of attributes.')
            mergedLinesString = self.fixAttributeChangeFlag(node=node, networkLayer=networkLayer)
        elif reasonType == 5:
            # original message: self.tr('Node was flagged upon classification (probably cannot be an ending hidrography node).')
            line = self.flipInvalidLine(node=node, networkLayer=networkLayer, validLines=connectedValidLines, geomType=geomType)
            if line:
                flippedLinesIds.append(str(line.id()))
                flippedLines.append(line)
                # if a line is flipped it must be changed in self.nodeDict
                self.updateNodeDict(node=node, line=line, networkLayer=networkLayer, geomType=geomType)
        else:
            # in case, for some reason, a strange value is given to reasonType
            return [], ''
        # for speed-up
        initialNode = lambda x : self.getFirstNode(lyr=networkLayer, feat=x, geomType=geomType)
        lastNode = lambda x : self.getLastNode(lyr=networkLayer, feat=x, geomType=geomType)
        # reclassification re-evalution is only needed if lines were flipped
        if flippedLinesIds:
            # re-classify nodes connected to flipped lines before re-checking
            # map is a for-loop in C
            reclassifyNodeAlias = lambda x : nodeLayer.changeAttributeValue(self.nodeIdDict[x], 2, int(self.reclassifyNodeType[x])) \
                                                if self.reclassifyNode(node=x, nodeLayer=nodeLayer) \
                                                else None
            map(reclassifyNodeAlias, map(initialNode, flippedLines) + map(lastNode, flippedLines))
            # check if node is fixed and update its dictionaries and invalidation reason
            valDict, invalidDict, reason = self.checkNodeValidity(node=node, connectedValidLines=connectedValidLines, \
                                            networkLayer=networkLayer, geomType=geomType, deltaLinesCheckList=deltaLinesCheckList)
        return flippedLinesIds, mergedLinesString

    def logAlteredFeatures(self, flippedLines, mergedLinesString):
        """
        Logs the list of flipped/merged lines, if any.
        :param flippedLines: (list-of-int) list of flipped lines.
        :param mergedLinesString: (str) text containing all merged lines (in the form of 'ID1 to ID2, ID3, to ID4')
        :return: (bool) whether or not a message was shown.
        """
        # building warning message
        warning = ''
        if flippedLines:
            warning = "".join([warning, self.tr("Lines that were flipped while directioning hidrography lines: {0}\n\n").format(", ".join(flippedLines))])
        elif mergedLinesString:
            warning = "".join([warning, self.tr("Lines that were merged while directioning hidrography lines: {0}\n\n").format(mergedLinesString)])
        if warning:
            # warning is only raised when there were flags fixed
            warning = "".join([self.tr('\n{0}: Flipped/Merged Lines\n').format(self.processAlias), warning])
            QgsMessageLog.logMessage(warning, "DSG Tools Plugin", QgsMessageLog.CRITICAL)
            return True
        return False

    def getNodeTypeDictFromNodeLayer(self, networkNodeLayer):
        """
        Get all node info (dictionaries for start/end(ing) lines and node type) from node layer.
        :param networkNodeLayer: (QgsVectorLayer) network node layer.
        :return: (tuple-of-dict) node type dict and node id dict, respectively
        """
        nodeTypeDict, nodeIdDict = dict(), dict()
        isMulti = QgsWKBTypes.isMultiType(int(networkNodeLayer.wkbType()))
        for feat in networkNodeLayer.getFeatures():
            if isMulti:
                node = feat.geometry().asMultiPoint()[0]                    
            else:
                node = feat.geometry().asPoint()
            nodeTypeDict[node] = feat['node_type']
            nodeIdDict[node] = feat.id()
        return nodeTypeDict, nodeIdDict

    def clearAuxiliaryLinesLayer(self, invalidLinesLayer, lineIdList=None, commitToLayer=False):
        """
        Clears all (or a given list of points) invalid lines from auxiliary lines layer.
        :param invalidLinesLayer: (QgsVectorLayer) invalid lines layer.
        :param lineIdList: (list-of-int) list of lines IDs to be cleared from layer.
        :param commitToLayer: (bool) indicates whether changes should be commited to layer.
        """
        # invalid reason texts
        invalidReason = self.tr('Connected to invalid hidrography node.')
        nonVisitedReason = self.tr('Line not yet visited.')
        invalidLinesLayer.beginEditCommand('Clear Invalid Lines')
        if lineIdList is None:
            # define a function to get only feature ids for invalid lines registered in invalidLinesLayer and use it in map, for speed-up
            getInvalidLineFunc = lambda feat : feat.id() if feat['reason'] in [invalidReason, nonVisitedReason] else -9999
            # list/set combination to remove possible duplicates of -9999 and avoid unnecessary calculation
            lineIdList = list(set(map(getInvalidLineFunc, invalidLinesLayer.getFeatures())))
            if -9999 in lineIdList:
                lineIdList.remove(-9999)
        invalidLinesLayer.deleteFeatures(lineIdList)
        invalidLinesLayer.endEditCommand()
        # commit changes to LAYER
        if commitToLayer:
            invalidLinesLayer.commitChanges()

    def createNewInvalidLineFeature(self, feat_geom, networkLayerName, fid, reason, fields, dimension=1, user_fixed='f', geometry_column='geom'):
        """
        Creates a new feature to be added to invalid lines layer.
        :param feat_geom: (QgsGeometry) 
        :param networkLayerName: (str) network layer name.
        :param fid: (int) invalid line ID.
        :param reason: (str) reason of line invalidation.
        :param fields: (QgsFields) object containing all fields from layer.
        :param dimension: (int) invalidation geometry type code.
        :param user_fixed: (str) 't' or 'f' indicating whether user has fixed issue.
        :param geometry_column: (str) name for geometry column persisted in database.
        :return: (QgsFeature) new feature.
        """
        # set attribute map and create new feture
        feat = QgsFeature(fields)
        # set geometry
        feat.setGeometry(feat_geom)
        feat['layer'] = networkLayerName
        feat['process_name'] = self.processAlias
        feat['feat_id'] = fid
        feat['reason'] = reason
        feat['dimension'] = dimension
        feat['user_fixed'] = user_fixed
        feat['geometry_column'] = geometry_column
        return feat

    def fillAuxiliaryLinesLayer(self, invalidLinesLayer, invalidLinesDict, nonValidatedLines, networkLayerName, commitToLayer=False):
        """
        Populate from auxiliary lines layer with all invalid lines.
        :param invalidLinesLayer: (QgsVectorLayer) hidrography nodes layer.
        :param invalidLinesDict: (dict) dictionary containing all invalid lines to be displayed.
        :param nonValidatedLines: (set) set of all non-validated network lines.
        :param commitToLayer: (bool) indicates whether changes should be commited to layer.
        """
        # if table is going to be filled, then it needs to be cleared first
        self.clearAuxiliaryLinesLayer(invalidLinesLayer=invalidLinesLayer, commitToLayer=commitToLayer)
        # get fields from layer in order to create new feature with the same attribute map
        fields = invalidLinesLayer.fields()
        # prepare generic variables that will be reused
        invalidReason = self.tr('Connected to invalid hidrography node.')
        nonVisitedReason = self.tr('Line not yet visited.')
        invalidLinesLayer.beginEditCommand('Add invalid lines')
        # to avoid unnecessary calculation inside loop
        nodeTypeKeys = self.nodeTypeDict.keys()
        # initiate new features list
        featList = []
        # pre-declaring method to make it faster
        newInvalidFeatFunc = lambda x : self.createNewInvalidLineFeature(feat_geom=x[0], networkLayerName=networkLayerName, \
                                            fid=x[1], reason=invalidReason, fields=fields)
        newNonVisitedFeatFunc = lambda x : self.createNewInvalidLineFeature(feat_geom=x[0], networkLayerName=networkLayerName, \
                                            fid=x[1], reason=nonVisitedReason, fields=fields)
        # add all non-validated features
        for line in nonValidatedLines:
            # create new feture
            feat = newNonVisitedFeatFunc([line.geometry(), line.id()])
            # add it to new features list
            featList.append(feat)
        # add invalid lines
        for lineId, line in invalidLinesDict.iteritems(): 
            # create new feture
            feat = newInvalidFeatFunc([line.geometry(), lineId])
            # add it to new features list
            featList.append(feat)
        invalidLinesLayer.addFeatures(featList)
        invalidLinesLayer.endEditCommand()
        if commitToLayer:
            invalidLinesLayer.commitChanges()

    def execute(self):
        """
        Structures and executes the process.
        :return: (int) execution code.
        """
        QgsMessageLog.logMessage(self.tr('Starting ')+self.getName()+self.tr(' Process.'), "DSG Tools Plugin", QgsMessageLog.CRITICAL)
        self.startTimeCount()
        # only selected option set for createNetworkNode object
        self.createNetworkNodesProcess.parameters['Only Selected'] = False
        try:
            self.setStatus(self.tr('Running'), 3) #now I'm running!
            self.abstractDb.deleteProcessFlags(self.getName()) #erase previous flags
            # node type should not be calculated OTF for comparison (db data is the one perpetuated)
            # setting all method variables
            hidSinkLyrKey = self.parameters['Sink Layer']
            networkLayerKey = self.parameters['Network Layer']
            refKey, classesWithElemKeys = self.parameters['Reference and Water Body Layers']
            waterBodyClassesKeys = classesWithElemKeys
            # preparing hidrography lines layer
            # remake the key from standard string
            k = ('{},{},{},{},{}').format(
                                          networkLayerKey.split('.')[0],\
                                          networkLayerKey.split('.')[1].split(r' (')[0],\
                                          networkLayerKey.split('(')[1].split(', ')[0],\
                                          networkLayerKey.split('(')[1].split(', ')[1],\
                                          networkLayerKey.split('(')[1].split(', ')[2].replace(')', '')
                                         )
            hidcl = self.networkClassesWithElemDict[k]
            hidNodeLyrKey = self.parameters['Node Layer']
            # remake the key from standard string
            k = ('{},{},{},{},{}').format(
                                        hidNodeLyrKey.split('.')[0],\
                                        hidNodeLyrKey.split('.')[1].split(r' (')[0],\
                                        hidNodeLyrKey.split('(')[1].split(', ')[0],\
                                        hidNodeLyrKey.split('(')[1].split(', ')[1],\
                                        hidNodeLyrKey.split('(')[1].split(', ')[2].replace(')', '')
                                        )
            nodecl = self.nodeClassesWithElemDict[k]
            # preparing the list of water bodies classes
            waterBodyClasses = []
            for key in waterBodyClassesKeys:
                wbc = self.classesWithElemDict[key]
                waterBodyClasses.append(self.loadLayerBeforeValidationProcess(wbc))
            # preparing water sink layer
            if hidSinkLyrKey and hidSinkLyrKey != self.tr('Select Layer'):
                # remake the key from standard string
                k = ('{},{},{},{},{}').format(
                                          hidSinkLyrKey.split('.')[0],\
                                          hidSinkLyrKey.split('.')[1].split(r' (')[0],\
                                          hidSinkLyrKey.split('(')[1].split(', ')[0],\
                                          hidSinkLyrKey.split('(')[1].split(', ')[1],\
                                          hidSinkLyrKey.split('(')[1].split(', ')[2].replace(')', '')
                                         )
                sinkcl = self.sinkClassesWithElemDict[k]
                waterSinkLayer = self.loadLayerBeforeValidationProcess(sinkcl)
            else:
                # if no sink layer is selected, layer should be ignored
                waterSinkLayer = None
            # preparing reference layer
            refcl = self.classesWithElemDict[refKey]
            frameLayer = self.loadLayerBeforeValidationProcess(refcl)
            # getting dictionaries of nodes information 
            frame = self.createNetworkNodesProcess.getFrameOutterBounds(frameLayer=frameLayer)
            # getting network lines and nodes layers
            networkNodeLayer = self.loadLayerBeforeValidationProcess(nodecl)
            networkLayer = self.loadLayerBeforeValidationProcess(hidcl)
            # start editting network layer in order to be able to flip/merge features from it
            networkLayer.startEditing()
            # start editting node layer in order to be able to reclassify nodes
            networkNodeLayer.startEditing()
            searchRadius = self.parameters['Search Radius']
            networkLayerGeomType = networkLayer.geometryType()
            # declare reclassification function from createNetworkNodesProcess object - parameter is [node, nodeTypeDict] 
            self.classifyNode = lambda x : self.createNetworkNodesProcess.nodeType(nodePoint=x[0], networkLayer=networkLayer, frameLyrContourList=frame, \
                                    waterBodiesLayers=waterBodyClasses, searchRadius=searchRadius, waterSinkLayer=waterSinkLayer, \
                                    nodeTypeDict=x[1], networkLayerGeomType=networkLayerGeomType)
            # getting node info from network node layer
            self.nodeDict = self.createNetworkNodesProcess.identifyAllNodes(networkLayer=networkLayer)
            # update createNetworkNodesProcess object node dictionary
            self.createNetworkNodesProcess.nodeDict = self.nodeDict
            self.nodeTypeDict, self.nodeIdDict = self.getNodeTypeDictFromNodeLayer(networkNodeLayer=networkNodeLayer)
            # initiate nodes, invalid/valid lines dictionaries
            nodeFlags, inval, val = dict(), dict(), dict()
            # cycle count start
            cycleCount = 0
            # get max amount of orientation cycles
            MAX_AMOUNT_CYCLES = self.parameters['Max. Directioning Cycles']
            MAX_AMOUNT_CYCLES = MAX_AMOUNT_CYCLES if MAX_AMOUNT_CYCLES > 0 else 1
            # field index for node type intiated
            for f in networkNodeLayer.getFeatures():
                # just to get field index
                fieldIndex = f.fieldNameIndex('node_type')
                break
            # validation method FINALLY starts...
            # to speed up modifications made to layers
            networkNodeLayer.beginEditCommand('Reclassify Nodes')
            networkLayer.beginEditCommand('Flip/Merge Lines')
            while True:
                # if self.parameters['Only Selected']:
                #     # in case directioning is to be executed over selected lines
                #     nodeListSelectedLines = None
                #     pass
                # make it recursive in order to not get stuck after all possible initial fixes
                nodeFlags_, inval_, val_ = self.directNetwork(networkLayer=networkLayer, nodeLayer=networkNodeLayer)
                cycleCount += 1
                # Log amount of cycles completed
                cycleCountLog = self.tr("Cycle {0} completed (maximum of {1}).").format(cycleCount, MAX_AMOUNT_CYCLES)
                QgsMessageLog.logMessage(cycleCountLog, "DSG Tools Plugin", QgsMessageLog.CRITICAL)
                self.reclassifyNodeType = dict()
                # stop conditions: max amount of cycles exceeded, new flags is the same as previous flags (there are no new issues) and no change
                # change to valid lines list was made (meaning that the algorithm did not change network state) or no flags found
                if (cycleCount == MAX_AMOUNT_CYCLES) or (not nodeFlags_) or (set(nodeFlags.keys()) == set(nodeFlags_.keys()) and val == val_):
                    # copy values to final dict
                    nodeFlags, inval, val = nodeFlags_, inval_, val_
                    # no more modifications to those layers will be done
                    networkLayer.endEditCommand()
                    networkNodeLayer.endEditCommand()
                    # try to load auxiliary line layer to fill it with invalid lines
                    try:
                        # try loading it
                        auxLinKey = 'aux,flags_validacao_l,geom,MULTILINESTRING,BASE TABLE'
                        lineClassesAuxDict = self.abstractDb.getGeomColumnDictV2(primitiveFilter=['l'], withElements=False, excludeValidation = False)
                        auxLinCl = lineClassesAuxDict[auxLinKey]
                        invalidLinesLayer = self.loadLayerBeforeValidationProcess(auxLinCl)
                        # free unnecessary memory usage
                        del lineClassesAuxDict, auxLinKey, auxLinCl
                        invalidLinesLayer.startEditing()
                        # get non-validated lines and add it to invalid lines layer as well
                        nonValidatedLines = set()
                        for line in networkLayer.getFeatures():
                            lineId = line.id()
                            if lineId in val or lineId in inval:
                                # ignore if line are validated
                                continue
                            nonValidatedLines.add(line)
                        self.fillAuxiliaryLinesLayer(invalidLinesLayer=invalidLinesLayer, invalidLinesDict=inval,\
                                                     nonValidatedLines=nonValidatedLines, networkLayerName=networkLayer.name())
                        invalidLinesLog = self.tr("Invalid lines were exposed in layer {0}).").format(invalidLinesLayer.name())
                        QgsMessageLog.logMessage(invalidLinesLog, "DSG Tools Plugin", QgsMessageLog.CRITICAL)
                    except:
                        pass
                    # check if there are any lines in both valid and invalid dicts and remove it from valid dict
                    vLines = val.keys()
                    iLines = inval.keys()
                    intersection = set(vLines) & set(iLines)
                    if intersection:
                        map(val.pop, intersection)
                        # remove unnecessary variables
                        del vLines, iLines, intersection
                    break
                # for the next iterations
                nodeFlags, inval, val = nodeFlags_, inval_, val_
                # pop all nodes to be popped and reset list
                for node in self.nodesToPop:
                    # those were nodes connected to lines that were merged and now are no longer to be used
                    self.nodeDict.pop(key, None)
                    self.createNetworkNodesProcess.nodeDict.pop(key, None)
                self.nodesToPop = []
            # if there are no starting nodes into network, a warning is raised
            if not isinstance(val, dict):
                # in that case method directNetwork() returns None, None, REASON
                QMessageBox.warning(self.iface.mainWindow(), self.tr('Error!'), self.tr('No initial node was found!'))
                self.finishedWithError()
                return 0
            # get number of selected features
            selectedFeatures = len(networkLayer.selectedFeatures())
            # if user set to select valid lines
            if self.parameters['Select All Valid Lines']:
                networkLayer.setSelectedFeatures(val.keys())
            # log percentage of network directed
            # if self.parameters['Only Selected']:
            #     percValid = float(len(val))*100.0/float(selectedFeatures)
            # else:
            percValid = float(len(val))*100.0/float(networkLayer.featureCount())
            if nodeFlags:
                msg = self.tr('{0} nodes may be invalid ({1:.2f}' + '%' +  ' of network is well directed). Check flags.')\
                            .format(len(nodeFlags), percValid)
            else:
                msg = self.tr('{1:.2f}' + '%' +  ' of network is well directed.')\
                            .format(len(nodeFlags), percValid)
            QgsMessageLog.logMessage(msg, "DSG Tools Plugin", QgsMessageLog.INFO)
            # getting recordList to be loaded to validation flag table
            recordList = self.buildFlagList(nodeFlags, 'validation', self.hidNodeLayerName, 'geom')
            if len(recordList) > 0 or inval:
                numberOfProblems = self.addFlag(recordList)
                self.setStatus(msg, 4) #Finished with flags
            else:
                msg = self.tr('Network has coherent directions.')
                self.setStatus(msg, 1) #Finished
            return 1
        except Exception as e:
            QgsMessageLog.logMessage(':'.join(e.args), "DSG Tools Plugin", QgsMessageLog.CRITICAL)
            self.finishedWithError()
            return 0
