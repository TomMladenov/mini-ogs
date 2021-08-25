import katpoint



if __name__ == "__main__":

    desired_az = 2.5
    desired_el = 3.5

    print("requested position: az:{} el:{}".format(desired_az, desired_el))

    pm = katpoint.PointingModel()
    model_keys = pm.keys()
    print(model_keys)

    pm.set([0.03182475704586052, 0.0, 0.0, 0.0, -0.016905005733684038, 0.008630185137265071, -0.012097433962651394, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    values = pm.values()
    print(values)

    az_actual, el_actual = pm.apply(desired_az, desired_el)
    print("actual position: az:{} el:{}".format(az_actual, el_actual))
