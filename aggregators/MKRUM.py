from copy import deepcopy
from datasetLoaders.DatasetInterface import DatasetInterface
from client import Client
from logger import logPrint
from typing import Dict, List
import torch
from aggregators.Aggregator import Aggregator
from torch import nn, device, Tensor


class MKRUMAggregator(Aggregator):
    def __init__(self, clients: List[Client], model: nn.Module, rounds: int, device: device, detectFreeRiders:bool, useAsyncClients:bool=False):
        super().__init__(clients, model, rounds, device, detectFreeRiders, useAsyncClients)

    def trainAndTest(self, testDataset: DatasetInterface):
        roundsError = torch.zeros(self.rounds)

        for r in range(self.rounds):
            logPrint("Round... ", r)

            self._shareModelAndTrainOnClients()
            models = self._retrieveClientModelsDict()

            self.model = self.aggregate(self.clients, models)

            roundsError[r] = self.test(testDataset)

        return roundsError

    def __computeModelDistance(self, mOrig: nn.Module, mDest: nn.Module) -> Tensor:
        paramsDest = mDest.named_parameters()
        dictParamsDest = dict(paramsDest)
        paramsOrig = mOrig.named_parameters()
        d1 = torch.tensor([]).to(self.device)
        d2 = torch.tensor([]).to(self.device)
        for name1, param1 in paramsOrig:
            if name1 in dictParamsDest:
                d1 = torch.cat((d1, dictParamsDest[name1].data.view(-1)))
                d2 = torch.cat((d2, param1.data.view(-1)))
        sim: Tensor = torch.norm(d1 - d2, p=2)
        return sim


    def aggregate(self, clients: List[Client], models: List[nn.Module]) -> nn.Module:
        empty_model = deepcopy(self.model)

        userNo = len(clients)
        # Number of Byzantine workers to be tolerated
        f = int((userNo - 3) / 2)
        th = userNo - f - 2
        mk = userNo - f
        # Compute distances for all users
        scores = torch.zeros(userNo)
        for client in clients:
            distances = torch.zeros((userNo, userNo))
            for client2 in clients:
                if client.id != client2.id:
                    distance = self.__computeModelDistance(
                        models[client.id].to(self.device),
                        models[client2.id].to(self.device),
                    )
                    distances[client.id][client2.id] = distance
            dd = distances[client.id][:].sort()[0]
            dd = dd.cumsum(0)
            scores[client.id] = dd[th]

        _, idx = scores.sort()
        selected_users = idx[: mk - 1] + 1
        # logPrint("Selected users: ", selected_users)

        comb = 0.0
        for client in clients:
            if client.id in selected_users:
                self._mergeModels(
                    models[client.id].to(self.device),
                    empty_model.to(self.device),
                    1 / mk,
                    comb,
                )
                comb = 1.0
