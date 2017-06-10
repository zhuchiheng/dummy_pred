#!/usr/bin/env python3

import os, sys, datetime, keras

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.append(PROJECT_ROOT)

import Common.config as config
import pandas as pd
from sqlalchemy.orm import sessionmaker
import numpy as np
import matplotlib.pyplot as plt
from keras.models import Sequential
from keras.layers import Dense, Activation, Flatten, Dropout, Convolution2D, BatchNormalization, Merge, LSTM, GRU
from keras.callbacks import ReduceLROnPlateau, ModelCheckpoint
from keras.optimizers import SGD, RMSprop
from keras.callbacks import EarlyStopping

# 参数设置
start_date = datetime.date(2016, 1, 1)
end_date = datetime.date(2016, 12, 30)
code = 'sz002166'
col = 'ma40'
data_splitter = 0.715

features = ['close', 'ma5', 'ma15', 'ma25', 'ma40']
timesteps = 10
prediction_step = 4
batch_size = 48  # 一天有48个五分钟

model_weight_file = os.path.join(config.MODEL_DIR, 'LSTMResearchMA40_weight.h5')
ds_cache_file = os.path.join(config.CACHE_DIR, 'LSTMResearchDataset.csv')
rs_cache_file = os.path.join(config.CACHE_DIR, 'LSTMResearchResult.csv')

np.random.seed(7)
if os.path.isfile(ds_cache_file):
    ds_df = pd.read_csv(ds_cache_file)
    dataset = ds_df.values
    dataset = dataset.reshape(dataset.shape[0], timesteps, len(features))

    rs_df = pd.read_csv(rs_cache_file)
    result = rs_df
else:
    # 获取数据
    session = sessionmaker()
    session.configure(bind=config.DB_CONN)
    db = session()
    sql = """
    SELECT
        `time`,
        `open`,
        `high`,
        `low`,
        `close`,
        `vol`,
        `count`,
        `ma5`,
        `ma15`,
        `ma25`,
        `ma40`
    FROM
        feature_extracted_stock_trading_5min
    WHERE
        `code` = '{0}'
            AND `time` > '{1}'
            AND `time` < '{2}' ;
    """.format(code, start_date, end_date)
    rs = db.execute(sql)
    df = pd.DataFrame(rs.fetchall())
    df.columns = ['time', 'open', 'high', 'low', 'close', 'vol', 'count', 'ma5', 'ma15', 'ma25', 'ma40']
    db.close()

    # 准备训练数据

    dataset = np.zeros((df.shape[0], timesteps, len(features)))
    result = pd.DataFrame(np.zeros([df.shape[0], 2]))
    i = 0
    for time, row in df.iterrows():
        if i >= timesteps:
            for t in range(timesteps):
                step = timesteps - t - 1
                rec = df.iloc[i - step, :]
                dataset[i, t] = rec[features].values

        if i < df.shape[0] - prediction_step:
            next_rec = df.iloc[i + prediction_step, :]
            result.iloc[i, 0] = next_rec[col]
            result.iloc[i, 1] = next_rec['time']
        i += 1
        pass

    result.columns = [col, 'time']
    result.index = result['time']
    result = result.drop('time', axis=1)

    # 掐头
    # df = df[timesteps:]
    dataset = dataset[timesteps:]
    result = result[timesteps:]

    # 去尾
    shift_size = dataset.shape[0] - prediction_step
    # df = df[:shift_size]
    dataset = dataset[:shift_size]
    result = result[:shift_size]

    # 缓存
    ds_df = pd.DataFrame(dataset.reshape(dataset.shape[0], -1))
    ds_df.to_csv(path_or_buf=ds_cache_file, index=False)

    rs_df = result
    rs_df.to_csv(path_or_buf=rs_cache_file, index=False)

print(("dataset: {}\t result:{}".format(dataset.shape[0], result.shape[0])))
total = int(dataset.shape[0] / batch_size) * batch_size
dataset = dataset[:total]
result = result[:total]

sep_pt = int(dataset.shape[0] * data_splitter)
sep_pt = int(int((sep_pt / batch_size)) * batch_size)

print(("after dropout:{}\t ".format(total)))
print(("sep_pt: {}".format(sep_pt)))

# 整理训练数据集
training_X = dataset[:sep_pt]
test_X = dataset[sep_pt:]

result_arr = result.values
training_y = result_arr[:sep_pt]
test_y = result_arr[sep_pt:]

# 图形输出
fig, ax = plt.subplots(figsize=(16, 8))
plt.title("5 mins K-Chart for {0} from {1} to {2}".format(code, start_date, end_date))

# 分割线
sep_max, sep_min = np.max(result) - (np.max(result) - np.min(result)), np.max(result)
sep_line = plt.plot(np.repeat(sep_pt - 1, 2), (sep_max, sep_min), color='black')

# 原始数据
training_display = training_y.reshape(-1)

prediction_display = test_y.reshape(-1)
# 用真实数据的最后一个来补位
# prediction_prepend = training_y.reshape(-1)
# prediction_display = np.hstack((prediction_prepend[prediction_prepend.shape[0]-prediction_step:], prediction_display))


raw_line = plt.plot(list(range(result.shape[0])), result.values, color='b')

training_line = plt.plot([sep_pt], [prediction_display[0]],
                         color='lime')
test_line = plt.plot([sep_pt], [prediction_display[0]],
                     color='r')

plt.xticks(np.arange(0, result.shape[0], 100), rotation=45, fontsize=10)
plt.ion()
plt.tight_layout()
plt.pause(0.5)


class DataVisualized(keras.callbacks.Callback):
    def __init__(self):
        super()
        self.epoch_c = 0
        pass

    def on_epoch_end(self, epoch, logs=None):
        if self.epoch_c % 5 == 0:
            training_pred = self.model.predict(training_X, batch_size=batch_size)
            training_line[0].set_data(np.arange(len(training_pred)), training_pred)

            test_pred = self.model.predict(test_X, batch_size=batch_size)
            test_line[0].set_data(np.arange(sep_pt, sep_pt + len(test_pred)), test_pred)
            plt.pause(0.5)
        self.epoch_c += 1
        pass


# 准备训练
reduce_lr = ReduceLROnPlateau(monitor='val_loss',
                              factor=0.2,
                              verbose=1,
                              patience=5,
                              min_lr=0.001)
checkpoint = ModelCheckpoint(model_weight_file,
                             monitor='val_loss',
                             verbose=1,
                             save_best_only=True,
                             save_weights_only=True,
                             mode='min',
                             period=1)
data_vis = DataVisualized()
model = Sequential([
    LSTM(100,
         batch_input_shape=(batch_size, timesteps, len(features)),
         return_sequences=False,
         stateful=True,
         init='glorot_uniform',
         inner_init='orthogonal',
         forget_bias_init='one',
         activation='tanh',
         inner_activation='hard_sigmoid',
         W_regularizer=None,
         U_regularizer=None,
         b_regularizer=None,
         dropout_W=0.0,
         dropout_U=0.0,
         name="lstm_1"),
    Dense(256, name="dense_2"),
    Dropout(0.4),
    Dense(128, name="dense_3"),
    Dense(1, name="output")
])

model.compile(optimizer='adadelta',
              loss='mse',
              metrics=['mae'])

if os.path.isfile(model_weight_file):
    model.load_weights(model_weight_file, by_name=True)

# training_pred = model.predict(training_X, batch_size=batch_size)
# training_line[0].set_data(np.arange(len(training_pred)), training_pred)
test_pred = model.predict(test_X, batch_size=batch_size)
test_line[0].set_data(np.arange(sep_pt, sep_pt + len(test_pred)), test_pred)
plt.pause(0.5)

model.fit(training_X, training_y,
          nb_epoch=2000,
          batch_size=batch_size,
          callbacks=[data_vis, checkpoint, reduce_lr],
          verbose=1,
          validation_data=(test_X, test_y))
