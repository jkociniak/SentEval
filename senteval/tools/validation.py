# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
#

"""
Validation and classification
(train)            :  inner-kfold classifier
(train, test)      :  kfold classifier
(train, dev, test) :  split classifier

"""
from __future__ import absolute_import, division, unicode_literals

import logging
import numpy as np
from senteval.tools.classifier import MLP

import sklearn
assert(sklearn.__version__ >= "0.18.0"), \
    "need to update sklearn to version >= 0.18.0"
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
import torch


def get_classif_name(classifier_config, usepytorch):
    if not usepytorch:
        modelname = 'sklearn-LogReg'
    else:
        nhid = classifier_config['nhid']
        optim = 'adam' if 'optim' not in classifier_config else classifier_config['optim']
        bs = 64 if 'batch_size' not in classifier_config else classifier_config['batch_size']
        modelname = 'pytorch-MLP-nhid%s-%s-bs%s' % (nhid, optim, bs)
    return modelname


# Pytorch version
class InnerKFoldClassifier(object):
    """
    (train) split classifier : InnerKfold.
    """
    def __init__(self, X, y, config):
        self.X = X
        self.y = y
        self.featdim = X.shape[1]
        self.nclasses = config['nclasses']
        self.seed = config['seed']
        self.max_iter = config['max_iter']
        self.devresults = []
        self.testresults = []
        self.usepytorch = config['usepytorch']
        self.classifier_config = config['classifier']
        self.modelname = get_classif_name(self.classifier_config, self.usepytorch)

        self.k = 5 if 'kfold' not in config else config['kfold']

    def run(self):
        logging.info('Training {0} with (inner) {1}-fold cross-validation'
                     .format(self.modelname, self.k))

        regs = [10**t for t in range(-5, -1)] if self.usepytorch else \
               [2**t for t in range(-2, 4, 1)]
        skf = StratifiedKFold(n_splits=self.k, shuffle=True, random_state=1111)
        innerskf = StratifiedKFold(n_splits=self.k, shuffle=True,
                                   random_state=1111)
        count = 0
        for train_idx, test_idx in skf.split(self.X, self.y):
            count += 1
            X_train, X_test = self.X[train_idx], self.X[test_idx]
            y_train, y_test = self.y[train_idx], self.y[test_idx]
            scores = []
            for reg in regs:
                regscores = []
                for inner_train_idx, inner_test_idx in innerskf.split(X_train, y_train):
                    X_in_train, X_in_test = X_train[inner_train_idx], X_train[inner_test_idx]
                    y_in_train, y_in_test = y_train[inner_train_idx], y_train[inner_test_idx]
                    if self.usepytorch:
                        X_in_train, X_in_test = torch.from_numpy(X_in_train).float(), torch.from_numpy(X_in_test).float()
                        y_in_train, y_in_test = torch.from_numpy(y_in_train).long(), torch.from_numpy(y_in_test).long()
                        clf = MLP(self.classifier_config, inputdim=self.featdim,
                                  nclasses=self.nclasses, l2reg=reg,
                                  seed=self.seed)
                        clf.fit(X_in_train, y_in_train,
                                validation_data=(X_in_test, y_in_test))
                        regscores.append(clf.score(X_in_test, y_in_test))
                    else:
                        clf = LogisticRegression(C=reg, random_state=self.seed)
                        clf.fit(X_in_train, y_in_train)
                        regscores.append(clf.score(X_in_test, y_in_test))
                scores.append(round(100*np.mean(regscores), 2))
            optreg = regs[np.argmax(scores)]
            logging.info('Best param found at split {0}: l2reg = {1} \
                with score {2}'.format(count, optreg, np.max(scores)))
            self.devresults.append(np.max(scores))

            if self.usepytorch:
                clf = MLP(self.classifier_config, inputdim=self.featdim,
                          nclasses=self.nclasses, l2reg=optreg,
                          seed=self.seed)
                X_train = torch.from_numpy(X_train).float()
                y_train = torch.from_numpy(y_train).long()
                clf.fit(X_train, y_train, validation_split=0.05)

                X_test = torch.from_numpy(X_test).float()
                y_test = torch.from_numpy(y_test).long()
            else:
                clf = LogisticRegression(C=optreg, random_state=self.seed)
                clf.fit(X_train, y_train)

            test_score = clf.score(X_test, y_test)
            self.testresults.append(round(100*test_score, 2))

        devaccuracy = round(np.mean(self.devresults), 2)
        testaccuracy = round(np.mean(self.testresults), 2)
        return devaccuracy, testaccuracy


class KFoldClassifier(object):
    """
    (train, test) split classifier : cross-validation on train.
    """
    def __init__(self, train, test, config):
        self.train = train
        self.test = test
        self.featdim = self.train['X'].shape[1]
        self.nclasses = config['nclasses']
        self.seed = config['seed']
        self.usepytorch = config['usepytorch']
        self.classifier_config = config['classifier']
        self.modelname = get_classif_name(self.classifier_config, self.usepytorch)

        self.k = 5 if 'kfold' not in config else config['kfold']

    def run(self):
        # cross-validation
        logging.info('Training {0} with {1}-fold cross-validation'
                     .format(self.modelname, self.k))
        regs = [10**t for t in range(-5, -1)] if self.usepytorch else \
               [2**t for t in range(-1, 6, 1)]
        skf = StratifiedKFold(n_splits=self.k, shuffle=True,
                              random_state=self.seed)
        scores = []

        for reg in regs:
            scanscores = []
            for train_idx, test_idx in skf.split(self.train['X'],
                                                 self.train['y']):
                # Split data
                X_train, y_train = self.train['X'][train_idx], self.train['y'][train_idx]

                X_test, y_test = self.train['X'][test_idx], self.train['y'][test_idx]

                # Train classifier
                if self.usepytorch:
                    clf = MLP(self.classifier_config, inputdim=self.featdim,
                              nclasses=self.nclasses, l2reg=reg,
                              seed=self.seed)
                    X_train, y_train = torch.from_numpy(X_train).float(), torch.from_numpy(y_train).long()
                    X_test, y_test = torch.from_numpy(X_test).float(), torch.from_numpy(y_test).long()
                    clf.fit(X_train, y_train, validation_data=(X_test, y_test))
                else:
                    clf = LogisticRegression(C=reg, random_state=self.seed)
                    clf.fit(X_train, y_train)
                score = clf.score(X_test, y_test)
                scanscores.append(score)
            # Append mean score
            scores.append(round(100*np.mean(scanscores), 2))

        # evaluation
        logging.info([('reg:' + str(regs[idx]), scores[idx])
                      for idx in range(len(scores))])
        optreg = regs[np.argmax(scores)]
        devaccuracy = np.max(scores)
        logging.info('Cross-validation : best param found is reg = {0} \
            with score {1}'.format(optreg, devaccuracy))

        logging.info('Evaluating...')
        if self.usepytorch:
            clf = MLP(self.classifier_config, inputdim=self.featdim,
                      nclasses=self.nclasses, l2reg=optreg,
                      seed=self.seed)

            X_train, y_train = torch.from_numpy(self.train['X']).float(), torch.from_numpy(self.train['y']).long()
            clf.fit(X_train, y_train, validation_split=0.05)

            X_test = torch.from_numpy(self.test['X']).float()
            y_test = torch.from_numpy(self.test['y']).long()
            testaccuracy = clf.score(X_test, y_test)
        else:
            clf = LogisticRegression(C=optreg, random_state=self.seed)
            clf.fit(self.train['X'], self.train['y'])
            testaccuracy = clf.score(self.test['X'], self.test['y'])

        yhat = clf.predict(X_test)
        testaccuracy = round(100*testaccuracy, 2)

        return devaccuracy, testaccuracy, yhat


class SplitClassifier(object):
    """
    (train, valid, test) split classifier.
    """
    def __init__(self, X, y, config):
        self.X = X
        self.y = y
        self.nclasses = config['nclasses']
        self.featdim = self.X['train'].shape[1]
        self.seed = config['seed']
        self.usepytorch = config['usepytorch']
        self.classifier_config = config['classifier']
        self.device = 'cpu' if 'device' not in config else config['device']
        self.modelname = get_classif_name(self.classifier_config, self.usepytorch)
        self.noreg = False if 'noreg' not in config else config['noreg']
        self.config = config

    def run(self):
        logging.info('Training {0} with standard validation..'
                     .format(self.modelname))
        regs = [10**t for t in range(-5, -1)] if self.usepytorch else \
               [2**t for t in range(-2, 4, 1)]
        if self.noreg:
            regs = [1e-9 if self.usepytorch else 1e9]
        scores = []
        for reg in regs:
            if self.usepytorch:
                clf = MLP(self.classifier_config, inputdim=self.featdim,
                          nclasses=self.nclasses, l2reg=reg,
                          seed=self.seed, device=self.device)

                # TODO: Find a hack for reducing nb epoches in SNLI
                X_train = torch.from_numpy(self.X['train']).float()
                y_train = torch.from_numpy(self.y['train']).long()
                X_val = torch.from_numpy(self.X['valid']).float()
                y_val = torch.from_numpy(self.y['valid']).long()
                clf.fit(X_train, y_train,
                        validation_data=(X_val, y_val))

            else:
                clf = LogisticRegression(C=reg, random_state=self.seed)
                clf.fit(self.X['train'], self.y['train'])
                X_val, y_val = self.X['valid'], self.y['valid']
            scores.append(round(100*clf.score(X_val,
                                y_val), 2))
        logging.info([('reg:'+str(regs[idx]), scores[idx])
                      for idx in range(len(scores))])
        optreg = regs[np.argmax(scores)]
        devaccuracy = np.max(scores)
        logging.info('Validation : best param found is reg = {0} with score \
            {1}'.format(optreg, devaccuracy))

        logging.info('Evaluating...')
        if self.usepytorch:
            clf = MLP(self.classifier_config, inputdim=self.featdim,
                      nclasses=self.nclasses, l2reg=optreg,
                      seed=self.seed, device=self.device)

            # TODO: Find a hack for reducing nb epoches in SNLI
            X_train = torch.from_numpy(self.X['train']).float()
            y_train = torch.from_numpy(self.y['train']).long()
            X_val = torch.from_numpy(self.X['valid']).float()
            y_val = torch.from_numpy(self.y['valid']).long()
            clf.fit(X_train, y_train,
                    validation_data=(X_val, y_val))

            X_test = torch.from_numpy(self.X['test']).float()
            y_test = torch.from_numpy(self.y['test']).long()
        else:
            clf = LogisticRegression(C=optreg, random_state=self.seed)
            clf.fit(self.X['train'], self.y['train'])
            X_test = self.X['test']
            y_test = self.y['test']

        testaccuracy = clf.score(X_test, y_test)
        testaccuracy = round(100*testaccuracy, 2)
        return devaccuracy, testaccuracy
