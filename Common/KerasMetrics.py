import keras.backend as K


def mean_error_rate(y_true, y_pred):
    return (K.mean(K.abs(y_pred - y_true))) / K.max(y_true)


def root_mean_squared_error(y_true, y_pred):
    return K.sqrt(K.mean(K.square(y_pred - y_true)))
