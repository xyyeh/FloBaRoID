#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

import numpy as np; # np.set_printoptions(formatter={'float': '{: 0.2f}'.format})
import matplotlib.pyplot as plt

# numeric regression
import iDynTree; iDynTree.init_helpers(); iDynTree.init_numpy_helpers()
import identificationHelpers

# symbolic regression
from robotran import idinvbar, invdynabar, delidinvbar

# TODO: load full model and programmatically cut off chain from certain joints/links to allow
# subtree identification
# TODO: change inertia values in urdf and save as output

import argparse
parser = argparse.ArgumentParser(description='Load measurements and URDF model to get inertial parameters.')
parser.add_argument('--model', required=True, type=str, help='the file to load the robot model from')
parser.add_argument('--measurements', required=True, type=str, help='the file to load the measurements from')
parser.add_argument('--plot', help='whether to plot measurements', action='store_true')
parser.add_argument('--explain', help='whether to explain parameters', action='store_true')
parser.set_defaults(plot=False)
args = parser.parse_args()

class Identification(object):
    def __init__(self):
        ## options
        self.robotranRegressor = False # use robotran symbolic regressor to estimate torques (else iDyntreee)
        #don't use both
        self.iDynSimulate = False # simulate torque using idyntree (instead of reading measurements)
        self.robotranSimulate = True # simulate torque using robotran (instead of reading measurements)

        self.start_offset = 200  #how many samples from the begginning of the measurements are skipped
        ## end options

        self.URDF_FILE = args.model
        self.measurements = np.load(args.measurements)
        self.num_samples = self.measurements['positions'].shape[0]
        print 'loaded {} measurement samples (using {})'.format(
                self.num_samples, self.num_samples-self.start_offset)
        self.num_samples-=self.start_offset

        # create generator instance and load model
        self.generator = iDynTree.DynamicsRegressorGenerator()
        self.generator.loadRobotAndSensorsModelFromFile(self.URDF_FILE)
        print 'loaded model {}'.format(self.URDF_FILE)

        # define what regressor type to use
        regrXml = '''
        <regressor>
          <jointTorqueDynamics>
            <joints>
                <joint>LShSag</joint>
                <joint>LShLat</joint>
                <joint>LShYaw</joint>
                <joint>LElbj</joint>
                <joint>LForearmPlate</joint>
                <joint>LWrj1</joint>
                <joint>LWrj2</joint>
            </joints>
          </jointTorqueDynamics>
        </regressor>'''
        # or use <allJoints/>
        self.generator.loadRegressorStructureFromString(regrXml)

        self.N_DOFS = self.generator.getNrOfDegreesOfFreedom()
        print '# DOFs: {}'.format(self.N_DOFS)

        # Get the number of outputs of the regressor
        self.N_OUT = self.generator.getNrOfOutputs()
        print '# outputs: {}'.format(self.N_OUT)

        # get initial inertia params (from urdf)
        self.N_PARAMS = self.generator.getNrOfParameters()
        print '# params: {}'.format(self.N_PARAMS)

        self.N_LINKS = self.generator.getNrOfLinks()
        print '# links: {} ({} fake)'.format(self.N_LINKS, self.generator.getNrOfFakeLinks())

        self.gravity_twist = iDynTree.Twist()
        self.gravity_twist.zero()
        self.gravity_twist.setVal(2, -9.81)

        self.jointNames = [self.generator.getDescriptionOfDegreeOfFreedom(dof) for dof in range(0, self.N_DOFS)]

        self.regressor_stack = np.empty(shape=(self.N_DOFS*self.num_samples, self.N_PARAMS))
        self.regressor_stack_sym = np.empty(shape=(self.N_DOFS*self.num_samples, 45))
        self.torques_stack = np.empty(shape=(self.N_DOFS*self.num_samples))

        self.helpers = identificationHelpers.IdentificationHelpers(self.N_PARAMS)

    def computeRegressors(self):
        if self.robotranRegressor:
            print("using robotran regressor")
        if self.iDynSimulate:
            print("using iDynTree to simulate robot dynamics")
        if self.robotranSimulate:
            print("using robotran to simulate robot dynamics")
        self.simulate = self.iDynSimulate or self.robotranSimulate
        if not self.simulate:
            print("using torque measurement data")

        sym_time = 0
        num_time = 0

        if self.simulate:
            dynComp = iDynTree.DynamicsComputations();
            dynComp.loadRobotModelFromFile(self.URDF_FILE);
            gravity = iDynTree.SpatialAcc();
            gravity.zero()
            gravity.setVal(2, -9.81);

        # get model parameters
        xStdModel = iDynTree.VectorDynSize(self.N_PARAMS)
        self.generator.getModelParameters(xStdModel)
        self.xStdModel = xStdModel.toNumPy()

        if self.robotranSimulate:
            #get urdf model parameters as base parameters (for robotran inverse kinematics)
            xStdModelBary = self.xStdModel.copy()
            self.helpers.paramsLink2Bary(xStdModelBary)
            m = np.zeros(self.N_DOFS+3)   #masses
            l = np.zeros((4, self.N_DOFS+3))  #com positions
            inert = np.zeros((10, 10))   #inertias
            for i in range(0, self.N_DOFS+2):
                m[i+1] = xStdModelBary[i*10]
                l[1, i+1] = xStdModelBary[i*10+1]
                l[2, i+1] = xStdModelBary[i*10+2]
                l[3, i+1] = xStdModelBary[i*10+3]
                inert[1, i+1] = xStdModelBary[i*10+4]     #xx w.r.t. com
                inert[2, i+1] = xStdModelBary[i*10+5]     #xy w.r.t. com
                inert[3, i+1] = xStdModelBary[i*10+6]     #xz w.r.t. com
                inert[4, i+1] = xStdModelBary[i*10+5]     #yx
                inert[5, i+1] = xStdModelBary[i*10+7]     #yy w.r.t. com
                inert[6, i+1] = xStdModelBary[i*10+8]     #yz w.r.t. com
                inert[7, i+1] = xStdModelBary[i*10+6]     #zx
                inert[8, i+1] = xStdModelBary[i*10+8]     #zy
                inert[9, i+1] = xStdModelBary[i*10+9]     #zz w.r.t. com

            model = iDynTree.Model()
            iDynTree.modelFromURDF(args.model, model)

            # get relative link positions
            d = np.zeros((4,10))  # should be 3 x 7, but invdynabar is funny and uses matlab indexing
            for i in range(1, self.N_DOFS+1):
                j = model.getJoint(i-1)
                #get position relative to parent joint
                l1 = j.getFirstAttachedLink()
                l2 = j.getSecondAttachedLink()
                t = j.getRestTransform(l1, l2)
                p = t.getPosition().toNumPy()
                d[1:4, i+2] = p

        self.torquesEst = list()
        self.tauMeasured = list()

        # loop over measurements records (skip some values from the start)
        # and get regressors for each system state
        for row in range(0+self.start_offset, self.num_samples+self.start_offset):
            if self.simulate:
                pos = self.measurements['target_positions'][row]
                vel = self.measurements['target_velocities'][row]
                acc = self.measurements['target_accelerations'][row]
            else:
                # read measurements
                pos = self.measurements['positions'][row]
                vel = self.measurements['velocities'][row]
                acc = self.measurements['accelerations'][row]
                torq = self.measurements['torques'][row]

            # use zero based again for matrices etc.
            row-=self.start_offset

            # system state
            q = iDynTree.VectorDynSize.fromPyList(pos)
            dq = iDynTree.VectorDynSize.fromPyList(vel)
            ddq = iDynTree.VectorDynSize.fromPyList(acc)

            if self.iDynSimulate:
                # calc torques with iDynTree dynamicsComputation class
                dynComp.setRobotState(q, dq, ddq, gravity)

                torques = iDynTree.VectorDynSize(self.N_DOFS)
                baseReactionForce = iDynTree.Wrench()   # assume zero

                # compute inverse dynamics with idyntree (simulate)
                dynComp.inverseDynamics(torques, baseReactionForce)
                torq = torques.toNumPy()
            elif self.robotranSimulate:
                torq = np.zeros(self.N_DOFS)

                self.xStdModelAsBase = np.zeros(48)
                delidinvbar.delidinvbar(self.xStdModelAsBase, m, l, inert, d)

                #get dynamics from robotran equations
                pad = [0,0]
                invdynabar.invdynabar(torq, np.concatenate(([0], pad, pos)), np.concatenate(([0], pad, vel)),
                    np.concatenate(([0], pad, acc)), np.concatenate(([0], self.xStdModelAsBase)), d)

            start = self.N_DOFS*row
            # use symobolic regressor to get numeric regressor matrix
            if self.robotranRegressor:
                with identificationHelpers.Timer() as t:
                    YSym = np.empty((7,48))
                    pad = [0,0]  # symbolic code expects values for two more (static joints)
                    idinvbar.idinvbar(YSym, np.concatenate([[0], pad, pos]),
                        np.concatenate([[0], pad, vel]), np.concatenate([[0], pad, acc]), d)
                    tmp = np.delete(YSym, (5,3,0), 1)   # remove unnecessary columns (numbers from generated code)
                    np.copyto(self.regressor_stack_sym[start:start+self.N_DOFS], tmp)
                sym_time += t.interval
            else:
                # get numerical regressor
                with identificationHelpers.Timer() as t:
                    self.generator.setRobotState(q,dq,ddq, self.gravity_twist)  # fixed base
                    self.generator.setTorqueSensorMeasurement(iDynTree.VectorDynSize.fromPyList(torq))

                    # get (standard) regressor
                    regressor = iDynTree.MatrixDynSize(self.N_OUT, self.N_PARAMS)
                    knownTerms = iDynTree.VectorDynSize(self.N_OUT)    # what are known terms useable for?
                    if not self.generator.computeRegressor(regressor, knownTerms):
                        print "Error during numeric computation of regressor"

                    YStd = regressor.toNumPy()
                    # stack on previous regressors
                    np.copyto(self.regressor_stack[start:start+self.N_DOFS], YStd)
                num_time += t.interval

            np.copyto(self.torques_stack[start:start+self.N_DOFS], torq)

        if self.robotranRegressor:
            print('Symbolic regressors took %.03f sec.' % sym_time)
        else:
            print('Numeric regressors took %.03f sec.' % num_time)

    def identify(self):
        # # inverse stacked regressors and identify parameter vector

        # get subspace basis (for projection to base regressor/parameters)
        subspaceBasis = iDynTree.MatrixDynSize()
        if not self.generator.computeFixedBaseIdentifiableSubspace(subspaceBasis):
        # if not generator.computeFloatingBaseIdentifiableSubspace(subspaceBasis):
            print "Error while computing basis matrix"

        # convert to numpy arrays
        YStd = self.regressor_stack
        YBaseSym = self.regressor_stack_sym
        tau = self.torques_stack
        B = subspaceBasis.toNumPy()

        print "YStd: {}".format(YStd.shape)
        print "YBaseSym: {}".format(YBaseSym.shape)
        print "tau: {}".format(tau.shape)

        # project regressor to base regressor, Y_base = Y_std*B
        YBase = np.dot(YStd, B)
        print "YBase: {}".format(YBase.shape)

        # invert equation to get parameter vector from measurements and model + system state values
        if self.robotranRegressor:
            YBaseSymInv = np.linalg.pinv(YBaseSym)

        YBaseInv = np.linalg.pinv(YBase)
        print "YBaseInv: {}".format(YBaseInv.shape)

        # TODO: get jacobian and contact force for each contact frame (when iDynTree allows it)
        # in order to also use FT sensors in hands and feet
        # assuming zero external forces for fixed base on trunk
        # jacobian = iDynTree.MatrixDynSize(6,6+N_DOFS)
        # generator.getFrameJacobian('arm', jacobian)

        if self.robotranRegressor:
            xBase = np.dot(YBaseSymInv, tau.T)
        else:
            xBase = np.dot(YBaseInv, tau.T) # - np.sum( YBaseInv*jacobian*contactForces )
        #print "The base parameter vector {} is \n{}".format(xBase.shape, xBase)

        # project back to standard parameters
        self.xStd = np.dot(B, xBase)
        # print "The standard parameter vector {} is \n{}".format(self.xStd.shape, self.xStd)

        # thresholding
        # zero_threshold = 0.0001
        # low_values_indices = np.absolute(self.xStd) < zero_threshold
        # self.xStd[low_values_indices] = self.xStdModel[low_values_indices] # replace close to zeros with cad values

        # # generate output

        if self.robotranRegressor:
            #tmp = np.delete(self.xStdModelAsBase, (5,3,0), 0)
            tauEst = np.dot(YBaseSym, xBase)
        else:
            # estimate torques again with regressor and parameters
            print "xStd: {}".format(self.xStd.shape)
            print "xStdModel: {}".format(self.xStdModel.shape)
        #    tauEst = np.dot(YStd, self.xStdModel) # idyntree standard regressor and parameters from URDF model
        #    tauEst = np.dot(YStd, self.xStd)    # idyntree standard regressor and estimated standard parameters
            tauEst = np.dot(YBase, xBase)   # idyntree base regressor and identified base parameters

        # put estimated torques in list of np vectors for plotting (NUM_SAMPLES*N_DOFSx1) -> (NUM_SAMPLESxN_DOFS)
        for i in range(0, tauEst.shape[0]):
            if i % self.N_DOFS == 0:
                tmp = np.zeros(self.N_DOFS)
                for j in range(0, self.N_DOFS):
                    tmp[j] = tauEst[i+j]
                self.torquesEst.append(tmp)
        self.torquesEst = np.array(self.torquesEst)

        if self.simulate:
            for i in range(0, tau.shape[0]):
                if i % self.N_DOFS == 0:
                    tmp = np.zeros(self.N_DOFS)
                    for j in range(0, self.N_DOFS):
                        tmp[j] = tau[i+j]
                    self.tauMeasured.append(tmp)
            self.tauMeasured = np.array(self.tauMeasured)
        else:
            self.tauMeasured = self.measurements['torques'][self.start_offset:, :]

    def explain(self):
        # some pretty printing of parameters
        if(args.explain):
            # optional: convert to COM-relative instead of frame origin-relative (linearized parameters)
            if not self.robotranRegressor:
                self.helpers.paramsLink2Bary(self.xStd)
            self.helpers.paramsLink2Bary(self.xStdModel)

            # collect values for parameters
            description = self.generator.getDescriptionOfParameters()
            idx_p = 0
            lines = list()
            for l in description.replace(r'Parameter ', '# ').replace(r'first moment', 'center').split('\n'):
                new = self.xStd[idx_p]
                old = self.xStdModel[idx_p]
                diff = old - new
                lines.append((old, new, diff, l))
                idx_p+=1
                if idx_p == len(self.xStd):
                    break

            column_widths = [15, 15, 7, 45]   # widths of the columns
            precisions = [8, 8, 3, 0]         # numerical precision

            # print column header
            template = ''
            for w in range(0, len(column_widths)):
                template += '|{{{}:{}}}'.format(w, column_widths[w])
            print template.format("Model", "Approx", "Error", "Description")

            # print values/description
            template = ''
            for w in range(0, len(column_widths)):
                if(type(lines[0][w]) == str):
                    template += '|{{{}:{}}}'.format(w, column_widths[w])
                else:
                    template += '|{{{}:{}.{}f}}'.format(w, column_widths[w], precisions[w])
            for l in lines:
                print template.format(*l)

    def plot(self):
        colors = [[ 0.97254902,  0.62745098,  0.40784314],
                  [ 0.0627451 ,  0.53333333,  0.84705882],
                  [ 0.15686275,  0.75294118,  0.37647059],
                  [ 0.90980392,  0.37647059,  0.84705882],
                  [ 0.84705882,  0.        ,  0.1254902 ],
                  [ 0.18823529,  0.31372549,  0.09411765],
                  [ 0.50196078,  0.40784314,  0.15686275]
                 ]

        datasets = [
                    ([self.tauMeasured], 'Measured Torques'),
                    ([self.torquesEst], 'Estimated Torques'),
                   ]
        print "torque diff: {}".format(self.tauMeasured - self.torquesEst)

        T = self.measurements['times'][self.start_offset:]
        for (data, title) in datasets:
            plt.figure()
            plt.title(title)
            for i in range(0, self.N_DOFS):
                for d_i in range(0, len(data)):
                    l = self.jointNames[i] if d_i == 0 else ''  # only put joint names in the legend once
                    plt.plot(T, data[d_i][:, i], label=l, color=colors[i], alpha=1-(d_i/2.0))
            leg = plt.legend(loc='best', fancybox=True, fontsize=10)
            leg.draggable()
        plt.show()
        self.measurements.close()

if __name__ == '__main__':
    # from IPython import embed; embed()

    try:
        identification = Identification()
        identification.computeRegressors()
        identification.identify()
        if(args.explain):
            identification.explain()
        if(args.plot):
            identification.plot()

    except Exception as e:
        if type(e) is not KeyboardInterrupt:
            # open ipdb when an exception happens
            import sys, ipdb, traceback
            type, value, tb = sys.exc_info()
            traceback.print_exc()
            ipdb.post_mortem(tb)
