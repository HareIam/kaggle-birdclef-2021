from typing import List
import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.metrics import accuracy_score, f1_score, recall_score, precision_score
import xgboost as xgb
import pickle
from . import metrics
from . import datasets
from . import feature_extraction

def train(
    candidate_df:pd.DataFrame,
    df:pd.DataFrame,
    num_kfolds:int,
    weight_rate:float=2.5,
    verbose:bool=False
):
    feature_names = feature_extraction.get_feature_names()
    if verbose:
        print("features", feature_names)
    X = candidate_df[feature_names].values
    y = candidate_df["target"].values
    groups = candidate_df["audio_id"]
    kf = StratifiedGroupKFold(n_splits=num_kfolds)
    for kfold_index, (_, valid_index) in enumerate(kf.split(X, y, groups)):
        candidate_df.loc[valid_index, "fold"] = kfold_index
    oofa = np.zeros(len(y), dtype=np.float32)
    for kfold_index in range(num_kfolds):
        train_index = candidate_df[candidate_df["fold"] != kfold_index].index
        valid_index = candidate_df[candidate_df["fold"] == kfold_index].index
        X_train, y_train = X[train_index], y[train_index]
        X_valid, y_valid = X[valid_index], y[valid_index]
        # 正例の重みを weight_rate, 負例を1にする
        sample_weight = np.ones(y_train.shape)
        sample_weight[y_train==1] = weight_rate
        sample_weight_val = np.ones(y_valid.shape)
        sample_weight_val[y_valid==1] = weight_rate
        sample_weight_eval_set = [sample_weight, sample_weight_val]
        clf = xgb.XGBClassifier(
            objective = "binary:logistic",
        )
        clf.fit(
            X_train, y_train,
            eval_set = [
                (X_train, y_train),
                (X_valid, y_valid)
            ],
            eval_metric             = "logloss",
            verbose                 = None,
            early_stopping_rounds   = 20,
            sample_weight           = sample_weight,
            sample_weight_eval_set  = sample_weight_eval_set,
        )
        pickle.dump(clf, open(f"xgb_{kfold_index}.pkl", "wb"))
        oofa[valid_index] = clf.predict_proba(X_valid)[:,1]

    def f(th):
        _gdf = candidate_df[oofa > th].groupby(
            ["audio_id", "seconds"],
            as_index=False
        )["label"].apply(lambda _: " ".join(_))
        df2 = pd.merge(
            df[["audio_id", "seconds", "birds"]],
            _gdf,
            how="left",
            on=["audio_id", "seconds"]
        )
        df2.loc[df2["label"].isnull(), "label"] = "nocall"
        return df2.apply(
            lambda _: metrics.get_metrics(_["birds"], _["label"])["f1"],
            axis=1
        ).mean()

    lb, ub = 0, 1
    for k in range(30):
        th1 = (2*lb + ub) / 3
        th2 = (lb + 2*ub) / 3
        if f(th1) < f(th2):
            lb = th1
        else:
            ub = th2
    th = (lb + ub) / 2
    print("best th: %.4f" % th)
    print("best F1: %.4f" % f(th))
    if verbose:
        oof = (oofa > th).astype(int)
        print("[details] Call or No call classirication")
        print("binary F1: %.4f" % f1_score(y, oof))
        print("gt positive ratio: %.4f" % np.mean(y))
        print("oof positive ratio: %.4f" % np.mean(oof))
        print("Accuracy: %.4f" % accuracy_score(y, oof))
        print("Recall: %.4f" % recall_score(y, oof))
        print("Precision: %.4f" % precision_score(y, oof))


