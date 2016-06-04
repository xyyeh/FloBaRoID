import time
from IPython import embed
import iDynTree
import numpy as np

class Timer(object):
    def __enter__(self):
        self.start = time.clock()
        return self

    def __exit__(self, *args):
        self.end = time.clock()
        self.interval = self.end - self.start

class Helpers(object):
    def __init__(self, n_params):
        self.n_params = n_params

    def bott_duffin(M, v):
        """
        Compute a constrained generalized inverse.
        Specifically, this is the Bott-Duffin inverse of M
        constrained to the orthogonal complement of v.
        This function assumes that v has rank 1,
        although Bott-Duffin inverses are also defined
        for inverses constrained to orthogonal complements
        of higher dimensional subspaces.
        @param M: a matrix
        @param v: a vector
        @return: the constrained generalized inverse of M
        """
        # check the shapes of the input matrix and vector
        n = len(v)
        if M.shape != (n, n):
            raise ValueError('M and v have incompatible shapes')
        # check that v is nonzero
        v_dot_v = np.inner(v, v)
        if not v_dot_v:
            raise ValueError('expected nonzero v')
        # compute the orthogonal projection onto v
        P = np.outer(v, v) / v_dot_v
        # compute the orthogonal projection onto the orthogonal complement of v
        I = np.eye(n)
        C = I - P
        # compute the constrained generalized inverse
        B = np.dot(C, np.linalg.inv(np.dot(M, C) + P))
        return B

    def checkPhysicalConsistency(self, params):
        """check params for physical consistency, expect params relative to link frame"""

        cons = {}
        for i in range(0, self.n_params):
            if (i % 10 == 0):   #for each link
                p_vec = iDynTree.Vector10()
                for j in range(0, 10):
                    p_vec.setVal(j, params[i+j])
                rbi = iDynTree.RigidBodyInertiaNonLinearParametrization()
                iDynTree.RigidBodyInertiaNonLinearParametrization.fromInertialParameters(rbi, p_vec)
                cons[i / 10] = rbi.isPhysicallyConsistent()
        return cons

    def inertiaParams2RotationalInertiaRaw(self, params):
        #take values from inertia parameter vector and create iDynTree RotationalInertiaRaw matrix
        #expects six parameter vector

        inertia = iDynTree.RotationalInertiaRaw()
        #xx of inertia matrix w.r.t. link origin
        value = params[0]
        inertia.setVal(0, 0, value)
        #xy
        value = params[1]
        inertia.setVal(0, 1, value)
        inertia.setVal(1, 0, value)
        #xz
        value = params[2]
        inertia.setVal(0, 2, value)
        inertia.setVal(2, 0, value)
        #yy
        value = params[3]
        inertia.setVal(1, 1, value)
        #yz
        value = params[4]
        inertia.setVal(1, 2, value)
        inertia.setVal(2, 1, value)
        #zz
        value = params[5]
        inertia.setVal(2, 2, value)
        return inertia

    def paramsLink2Bary(self, params):
        ## convert params from iDynTree values (relative to link frame) to values usable in URDF (barycentric)
        ## (params are changed in place)

        #mass is mass
        #com in idyntree is represented as first moment of mass, so com * mass. URDF uses com
        #inertia in idyntree is represented w.r.t. frame origin. URDF uses w.r.t com
        params = params.copy()
        for i in range(0, self.n_params):
            if (i % 10 == 0):   #for each link
                link_mass = params[i]
                #com
                com_x = params[i+1]
                com_y = params[i+2]
                com_z = params[i+3]
                if link_mass != 0:
                    params[i+1] = com_x / link_mass  #x of first moment -> x of com
                    params[i+2] = com_y / link_mass  #y of first moment -> y of com
                    params[i+3] = com_z / link_mass  #z of first moment -> z of com
                else:
                    params[i+1] = params[i+2] = params[i+3] = 0
                p_com = iDynTree.PositionRaw(params[i+1], params[i+2], params[i+3])

                #inertias
                rot_inertia_origin = self.inertiaParams2RotationalInertiaRaw(params[i+4:i+10])
                s_inertia = iDynTree.SpatialInertia(link_mass, p_com, rot_inertia_origin)
                rot_inertia_com = s_inertia.getRotationalInertiaWrtCenterOfMass()
                params[i+4] = rot_inertia_com.getVal(0, 0)    #xx w.r.t. com
                params[i+5] = rot_inertia_com.getVal(0, 1)    #xy w.r.t. com
                params[i+6] = rot_inertia_com.getVal(0, 2)    #xz w.r.t. com
                params[i+7] = rot_inertia_com.getVal(1, 1)    #yy w.r.t. com
                params[i+8] = rot_inertia_com.getVal(1, 2)    #yz w.r.t. com
                params[i+9] = rot_inertia_com.getVal(2, 2)    #zz w.r.t. com
        return params

    def paramsBary2Link(self, params):
        params = params.copy()
        for i in range(0, self.n_params):
            if (i % 10 == 0):   #for each link
                link_mass = params[i]
                #com
                com_x = params[i+1]
                com_y = params[i+2]
                com_z = params[i+3]
                params[i+1] = com_x * link_mass  #x of first moment of mass
                params[i+2] = com_y * link_mass  #y of first moment of mass
                params[i+3] = com_z * link_mass  #z of first moment of mass
                p_com = iDynTree.PositionRaw(params[i+1], params[i+2], params[i+3])

                #inertias
                rot_inertia_com = self.inertiaParams2RotationalInertiaRaw(params[i+4:i+10])
                s_inertia = iDynTree.SpatialInertia(link_mass, p_com, rot_inertia_com)
                s_inertia.fromRotationalInertiaWrtCenterOfMass(link_mass, p_com, rot_inertia_com)
                rot_inertia = s_inertia.getRotationalInertiaWrtFrameOrigin()
                params[i+4] = rot_inertia.getVal(0, 0)    #xx w.r.t. com
                params[i+5] = rot_inertia.getVal(0, 1)    #xy w.r.t. com
                params[i+6] = rot_inertia.getVal(0, 2)    #xz w.r.t. com
                params[i+7] = rot_inertia.getVal(1, 1)    #yy w.r.t. com
                params[i+8] = rot_inertia.getVal(1, 2)    #yz w.r.t. com
                params[i+9] = rot_inertia.getVal(2, 2)    #zz w.r.t. com

        return params

    def replaceParamsInURDF(self, input_urdf, output_urdf, new_params, link_names):
        """ set new inertia parameters from params and urdf_file, write to new temp file """

        import xml.etree.ElementTree as ET
        xStdBary = self.paramsLink2Bary(new_params)

        tree = ET.parse(input_urdf)
        for l in tree.findall('link'):
            if l.attrib['name'] in link_names:
                link_id = link_names.index(l.attrib['name'])
                l.find('inertial/mass').attrib['value'] = str(xStdBary[link_id*10])
                l.find('inertial/origin').attrib['xyz'] = '{} {} {}'.format(xStdBary[link_id*10+1],
                                                                            xStdBary[link_id*10+2],
                                                                            xStdBary[link_id*10+3])
                inert = l.find('inertial/inertia')
                inert.attrib['ixx'] = str(xStdBary[link_id*10+4])
                inert.attrib['ixy'] = str(xStdBary[link_id*10+5])
                inert.attrib['ixz'] = str(xStdBary[link_id*10+6])
                inert.attrib['iyy'] = str(xStdBary[link_id*10+7])
                inert.attrib['iyz'] = str(xStdBary[link_id*10+8])
                inert.attrib['izz'] = str(xStdBary[link_id*10+9])

        tree.write(output_urdf, xml_declaration=True)