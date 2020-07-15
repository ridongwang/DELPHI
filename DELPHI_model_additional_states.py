# Authors: Hamza Tazi Bouardi (htazi@mit.edu), Michael L. Li (mlli@mit.edu), Omar Skali Lami (oskali@mit.edu)
import pandas as pd
import numpy as np
import multiprocessing as mp
import time
from functools import partial
from scipy.integrate import solve_ivp
from scipy.optimize import minimize
from tqdm import tqdm_notebook as tqdm
from datetime import datetime, timedelta
from DELPHI_utils_V3 import (
    DELPHIDataCreator, get_initial_conditions, mape
)
from DELPHI_params_V3 import (
    get_default_parameter_list_and_bounds, n_cpu_default,
    validcases_threshold, IncubeD, RecoverID, RecoverHD, DetectD,
    VentilatedD, default_maxT, p_v, p_d, p_h, max_iter
)
import os
from os import path
import yaml


with open("config.yml", "r") as ymlfile:
    CONFIG = yaml.load(ymlfile, Loader=yaml.BaseLoader)
CONFIG_FILEPATHS = CONFIG["filepaths"]
USER_RUNNING = "server"
training_start_date = datetime(2020, 7, 9)
training_end_date = datetime(2020, 7, 15)
training_last_date = training_end_date - timedelta(days=1)
# Default training_last_date is up to day before now, but depends on what's the most recent historical data you have
n_days_to_train = (training_last_date - training_start_date).days


def check_cumulative_cases(input_table):
    correct = True
    count = input_table['day_since100'].iloc[0]
    for ind, row in input_table.iterrows():
        if count != row['day_since100']:
            correct = False
            break
        else:
            count += 1
    return correct


def solve_and_predict_area_additional_states(
        tuple_area_: tuple, yesterday_: str, day_after_yesterday_: str, allowed_deviation_: float,
        pastparameters_: pd.DataFrame, current_parameters_: pd.DataFrame,
):
    time_entering = time.time()
    continent, country, province = tuple_area_
    country_sub = country.replace(" ", "_")
    province_sub = province.replace(" ", "_")
    # if province_sub not in ["Michoacan"]:
    #     continue
    # if province_sub == "Michoacan" and country_sub == "Peru":
    #     continue
    if country_sub not in ["US", "Brazil", "Chile", "Colombia", "Russia", "South_Africa", "Mexico", "Peru"]:
        return None
    elif country_sub == "US":
        if province_sub not in [
             'Atlanta_Sandy_Springs_Alpharetta', 'Austin_Round_Rock_Georgetown', 'Baltimore_Columbia_Towson',
             'Birmingham_Hoover', 'Boston_Cambridge_Newton', 'Chicago_Naperville_Elgin', 'Cincinnati',
             'Cleveland_Elyria', 'Columbus', 'Dallas_Fort_Worth_Arlington', 'Detroit_Warren_Dearborn',
             'Durham_Chapel_Hill', 'Houston_The_Woodlands_Sugar_Land', 'Knoxville', 'Las_Vegas_Henderson_Paradise',
             'Los_Angeles_Long_Beach_Orange_County', 'Miami_Fort_Lauderdale_Pompano_Beach', 'Minneapolis',
             'Mobile', 'Nashville_Davidson_Murfreesboro_Franklin', 'New_Haven_Milford', 'New_Orleans_Metairie',
             'New_York_Newark_Jersey_City', 'Omaha_Council_Bluffs', 'Orlando_Kissimmee_Sanford',
             'Philadelphia_Camden_Wilmington', 'Phoenix', 'Pittsburgh', 'Rochester',  'San_Diego_Chula_Vista_Carlsbad',
             'San_Jose_Sunnyvale_Santa_Clara', 'Seattle_Tacoma_Bellevue', 'Sioux_Falls', 'St._Louis', 'Tucson',
             'Washington_Arlington_Alexandria'
        ]:
            return None
    elif country_sub in ["Brazil", "Chile", "Colombia", "Russia", "South_Africa", "Mexico", "Peru"]:
        if province_sub == "None":
            return None

    if current_parameters_ is not None:
        current_parameter = current_parameters_[
            (current_parameters_.Country == country) &
            (current_parameters_.Province == province)
            ].reset_index(drop=True)
        if len(current_parameter) > 0:
            print(
                f"Parameters already exist on {day_after_yesterday_} " +
                f"Continent={continent}, Country={country} and Province={province}"
            )
            return None

    if os.path.exists(PATH_TO_DATA_SANDBOX + f"processed/{country_sub}_J&J/Cases_{country_sub}_{province_sub}.csv"):
        print(country + ", " + province)
        totalcases = pd.read_csv(
            PATH_TO_DATA_SANDBOX + f"processed/{country_sub}_J&J/Cases_{country_sub}_{province_sub}.csv"
        )
        if check_cumulative_cases(totalcases) == False:
            print(
                f"###################### [ERROR] Cumulative case is not increasing: " +
                f"{day_after_yesterday_} Continent={continent}, Country={country} and Province={province}"
            )
            return None
        if totalcases.day_since100.max() < 8:
            print(f"Not enough cases for Continent={continent}, Country={country} and Province={province}")
            return None
        if pastparameters_ is not None:
            parameter_list_total = pastparameters_[
                (pastparameters_.Country == country) &
                (pastparameters_.Province == province)
                ].reset_index(drop=True)
            if len(parameter_list_total) > 0:
                parameter_list_line = parameter_list_total.iloc[-1, :].values.tolist()
                parameter_list = parameter_list_line[5:]
                assert len(parameter_list) == 11, f"Only have {len(parameter_list)} parameters, expected 11 since July8"
                # Allowing a 5% drift for states with past predictions, starting in the 5th position are the parameters
                param_list_lower = [x - 0.1 * abs(x) for x in parameter_list]
                param_list_upper = [x + 0.1 * abs(x) for x in parameter_list]
                bounds_params = [
                    (lower, upper)
                     for lower, upper in zip(param_list_lower, param_list_upper)
                ]
                date_day_since100 = pd.to_datetime(parameter_list_line[3])
                validcases = totalcases[
                    (totalcases.day_since100 >= 0) &
                    (totalcases.date <= str(pd.to_datetime(day_after_yesterday_).date()))
                    ][["date", "day_since100", "case_cnt", "death_cnt"]].reset_index(drop=True)
            else:
                # Otherwise use established lower/upper bounds
                date_day_since100 = pd.to_datetime(totalcases.loc[totalcases.day_since100 == 0, "date"].iloc[-1])
                validcases = totalcases[
                    (totalcases.day_since100 >= 0) &
                    (totalcases.date <= str(pd.to_datetime(day_after_yesterday_).date()))
                ][["date", "day_since100", "case_cnt", "death_cnt"]].reset_index(drop=True)
                parameter_list, bounds_params = get_default_parameter_list_and_bounds(validcases)
                assert len(parameter_list) == 11, f"Only have {len(parameter_list)} parameters, expected 11 since July8"
        else:
            # Otherwise use established lower/upper bounds
            date_day_since100 = pd.to_datetime(totalcases.loc[totalcases.day_since100 == 0, "date"].iloc[-1])
            validcases = totalcases[
                (totalcases.day_since100 >= 0) &
                (totalcases.date <= str(pd.to_datetime(day_after_yesterday_).date()))
            ][["date", "day_since100", "case_cnt", "death_cnt"]].reset_index(drop=True)
            parameter_list, bounds_params = get_default_parameter_list_and_bounds(validcases)
            assert len(parameter_list) == 11, f"Only have {len(parameter_list)} parameters, expected 11 since July8"
        # Now we start the modeling part:
        if len(validcases) > validcases_threshold:
            PopulationT = popcountries[
                (popcountries.Country == country) & (popcountries.Province == province)
                ].pop2016.iloc[-1]
            # We do not scale
            N = PopulationT
            PopulationI = validcases.loc[0, "case_cnt"]
            PopulationR = validcases.loc[0, "death_cnt"] * 5
            PopulationD = validcases.loc[0, "death_cnt"]
            PopulationCI = PopulationI - PopulationD - PopulationR
            """
            Fixed Parameters based on meta-analysis:
            p_h: Hospitalization Percentage
            RecoverHD: Average Days till Recovery
            VentilationD: Number of Days on Ventilation for Ventilated Patients
            maxT: Maximum # of Days Modeled
            p_d: Percentage of True Cases Detected
            p_v: Percentage of Hospitalized Patients Ventilated,
            balance: Ratio of Fitting between cases and deaths
            """
            # Currently fit on alpha, a and b, r_dth,
            # & initial condition of exposed state and infected state
            # Maximum timespan of prediction, defaulted to go to 15/06/2020
            maxT = (default_maxT - date_day_since100).days + 1
            """ Fit on Total Cases """
            t_cases = validcases["day_since100"].tolist() - validcases.loc[0, "day_since100"]
            validcases_nondeath = validcases["case_cnt"].tolist()
            validcases_death = validcases["death_cnt"].tolist()
            balance = validcases_nondeath[-1] / max(validcases_death[-1], 10) / 3
            fitcasesnd = validcases_nondeath
            fitcasesd = validcases_death
            GLOBAL_PARAMS_FIXED = (
                N, PopulationCI, PopulationR, PopulationD, PopulationI, p_d, p_h, p_v
            )

            def model_covid(
                    t, x, alpha, days, r_s, r_dth, p_dth, r_dthdecay, k1, k2, jump, t_jump, std_normal
            ):
                """
                SEIR + Undetected, Deaths, Hospitalized, corrected with ArcTan response curve
                alpha: Infection rate
                days: Median day of action
                r_s: Median rate of action
                p_dth: Mortality rate
                k1: Internal parameter 1
                k2: Internal parameter 2
                jump: size of the jump for the resurgence in cases/deaths modeled with normal distribution
                t_jump: when the jump for the resurgence in cases/deaths reaches the peak
                std_normal: standard deviation of the normal distribution
                y = [0 S, 1 E,  2 I, 3 AR, 4 DHR,  5 DQR, 6 AD,
                7 DHD, 8 DQD, 9 R, 10 D, 11 TH, 12 DVR,13 DVD, 14 DD, 15 DT]
                """
                r_i = np.log(2) / IncubeD  # Rate of infection leaving incubation phase
                r_d = np.log(2) / DetectD  # Rate of detection
                r_ri = np.log(2) / RecoverID  # Rate of recovery not under infection
                r_rh = np.log(2) / RecoverHD  # Rate of recovery under hospitalization
                r_rv = np.log(2) / VentilatedD  # Rate of recovery under ventilation
                gamma_t = (2 / np.pi) * np.arctan(-(t - days) / 20 * r_s) + 1 + jump * np.exp(
                    -(t - t_jump) ** 2 / (2 * std_normal ** 2)
                )
                p_dth_mod = (2 / np.pi) * (p_dth - 0.01) * (np.arctan(- t / 20 * r_dthdecay) + np.pi / 2) + 0.01
                assert len(x) == 16, f"Too many input variables, got {len(x)}, expected 16"
                S, E, I, AR, DHR, DQR, AD, DHD, DQD, R, D, TH, DVR, DVD, DD, DT = x
                # Equations on main variables
                dSdt = -alpha * gamma_t * S * I / N
                dEdt = alpha * gamma_t * S * I / N - r_i * E
                dIdt = r_i * E - r_d * I
                dARdt = r_d * (1 - p_dth_mod) * (1 - p_d) * I - r_ri * AR
                dDHRdt = r_d * (1 - p_dth_mod) * p_d * p_h * I - r_rh * DHR
                dDQRdt = r_d * (1 - p_dth_mod) * p_d * (1 - p_h) * I - r_ri * DQR
                dADdt = r_d * p_dth_mod * (1 - p_d) * I - r_dth * AD
                dDHDdt = r_d * p_dth_mod * p_d * p_h * I - r_dth * DHD
                dDQDdt = r_d * p_dth_mod * p_d * (1 - p_h) * I - r_dth * DQD
                dRdt = r_ri * (AR + DQR) + r_rh * DHR
                dDdt = r_dth * (AD + DQD + DHD)
                # Helper states (usually important for some kind of output)
                dTHdt = r_d * p_d * p_h * I
                dDVRdt = r_d * (1 - p_dth_mod) * p_d * p_h * p_v * I - r_rv * DVR
                dDVDdt = r_d * p_dth_mod * p_d * p_h * p_v * I - r_dth * DVD
                dDDdt = r_dth * (DHD + DQD)
                dDTdt = r_d * p_d * I
                return [
                    dSdt, dEdt, dIdt, dARdt, dDHRdt, dDQRdt, dADdt, dDHDdt, dDQDdt,
                    dRdt, dDdt, dTHdt, dDVRdt, dDVDdt, dDDdt, dDTdt
                ]

            def residuals_totalcases(params):
                """
                Wanted to start with solve_ivp because figures will be faster to debug
                params: (alpha, days, r_s, r_dth, p_dth, k1, k2, jump, t_jump, std_normal),
                fitted parameters of the model
                """
                # Variables Initialization for the ODE system
                alpha, days, r_s, r_dth, p_dth, r_dthdecay, k1, k2, jump, t_jump, std_normal = params
                params = (
                    max(alpha, 0), days, max(r_s, 0), max(r_dth, 0), max(min(p_dth, 1), 0), max(min(r_dthdecay, 1), 0),
                    max(k1, 0), max(k2, 0), max(jump, 0), max(t_jump, 0), max(std_normal, 0)
                )
                x_0_cases = get_initial_conditions(
                    params_fitted=params,
                    global_params_fixed=GLOBAL_PARAMS_FIXED
                )
                x_sol = solve_ivp(
                    fun=model_covid,
                    y0=x_0_cases,
                    t_span=[t_cases[0], t_cases[-1]],
                    t_eval=t_cases,
                    args=tuple(params)
                ).y
                weights = list(range(1, len(fitcasesnd) + 1))
                # weights[-15:] =[x + 50 for x in weights[-15:]]
                residuals_value = sum(
                    np.multiply((x_sol[15, :] - fitcasesnd) ** 2, weights)
                    + balance * balance * np.multiply((x_sol[14, :] - fitcasesd) ** 2, weights)
                )
                return residuals_value

            output = minimize(
                residuals_totalcases,
                parameter_list,
                method='tnc',  # Can't use Nelder-Mead if I want to put bounds on the params
                bounds=bounds_params,
                options={'maxiter': max_iter}
            )
            best_params = output.x
            t_predictions = [i for i in range(maxT)]

            def solve_best_params_and_predict(optimal_params):
                # Variables Initialization for the ODE system
                x_0_cases = get_initial_conditions(
                    params_fitted=optimal_params,
                    global_params_fixed=GLOBAL_PARAMS_FIXED
                )
                x_sol_best = solve_ivp(
                    fun=model_covid,
                    y0=x_0_cases,
                    t_span=[t_predictions[0], t_predictions[-1]],
                    t_eval=t_predictions,
                    args=tuple(optimal_params),
                ).y
                return x_sol_best

            x_sol_final = solve_best_params_and_predict(best_params)
            data_creator = DELPHIDataCreator(
                x_sol_final=x_sol_final, date_day_since100=date_day_since100, best_params=best_params,
                continent=continent, country=country, province=province, testing_data_included=False
            )
            # Creating the parameters dataset for this (Continent, Country, Province)
            mape_data = (
                    mape(fitcasesnd, x_sol_final[15, :len(fitcasesnd)]) +
                    mape(fitcasesd, x_sol_final[14, :len(fitcasesd)])
            ) / 2
            if len(fitcasesnd) > 15:
                mape_data_2 = (
                        mape(fitcasesnd[-15:], x_sol_final[15, len(fitcasesnd) - 15:len(fitcasesnd)]) +
                        mape(fitcasesd[-15:], x_sol_final[14, len(fitcasesnd) - 15:len(fitcasesd)])
                ) / 2
                print(f"In-Sample MAPE Last 15 Days {country, province}: {round(mape_data_2, 3)} %")
            df_parameters_cont_country_prov = data_creator.create_dataset_parameters(mape_data)
            # Creating the datasets for predictions of this (Continent, Country, Province)
            df_predictions_since_today_cont_country_prov, df_predictions_since_100_cont_country_prov = (
                data_creator.create_datasets_predictions()
            )
            print(
                f"Finished predicting for Continent={continent}, Country={country} and Province={province} in " +
                f"{round(time.time() - time_entering, 2)} seconds"
            )
            return (
                df_parameters_cont_country_prov, df_predictions_since_today_cont_country_prov,
                df_predictions_since_100_cont_country_prov, output
            )
        else:  # len(validcases) <= 7
            print(f"Not enough historical data (less than a week)" +
                  f"for Continent={continent}, Country={country} and Province={province}")
            return None
    else:  # file for that tuple (country, province) doesn't exist in processed files
        print(
            f"file for that tuple does not exist {day_after_yesterday_} Continent={continent}, Country={country} and Province={province}"
        )
        return None


for n_days_before in range(n_days_to_train, 0, -1):
    yesterday = "".join(str(training_last_date.date() - timedelta(days=n_days_before)).split("-"))
    day_after_yesterday = "".join(str(pd.to_datetime(yesterday).date() + timedelta(days=1)).split("-"))
    print(yesterday, day_after_yesterday)
    print(f"Predictions with historical data up to {day_after_yesterday}, parameters from {yesterday}")
    PATH_TO_DATA_SANDBOX = CONFIG_FILEPATHS["data_sandbox"][USER_RUNNING]
    # PATH_TO_WEBSITE_PREDICTED = CONFIG_FILEPATHS["website"]["michael"]
    popcountries = pd.read_csv(
        PATH_TO_DATA_SANDBOX + f"processed/Population_Global.csv"
    )
    try:
        pastparameters = pd.read_csv(
            PATH_TO_DATA_SANDBOX + f"predicted/parameters/Parameters_J&J_{yesterday}.csv"
        )
    except:
        pastparameters = None
    try:
        current_parameters = pd.read_csv(
            PATH_TO_DATA_SANDBOX + f"predicted/parameters/Parameters_J&J_{day_after_yesterday}.csv"
        )
    except:
        current_parameters = None

    # Initalizing lists of the different dataframes that will be concatenated in the end
    list_df_global_predictions_since_today = []
    list_df_global_predictions_since_100_cases = []
    list_df_global_parameters = []
    obj_value = 0
    allowed_deviation = 0.02
    solve_and_predict_area_partial = partial(
        solve_and_predict_area_additional_states, yesterday_=yesterday, day_after_yesterday_=day_after_yesterday,
        pastparameters_=pastparameters, allowed_deviation_=allowed_deviation, current_parameters_=current_parameters,
    )
    popcountries["tuple_area"] = list(zip(popcountries.Continent, popcountries.Country, popcountries.Province))
    list_tuples = popcountries.tuple_area.tolist()
    with mp.Pool(n_cpu_default) as pool:
        for result_area in tqdm(
                pool.map_async(
                    solve_and_predict_area_partial, list_tuples,
                ).get(), total=len(list_tuples)
        ):
            if result_area is not None:
                (
                    df_parameters_cont_country_prov, df_predictions_since_today_cont_country_prov,
                    df_predictions_since_100_cont_country_prov, output
                ) = result_area
                obj_value = obj_value + output.fun
                # Then we add it to the list of df to be concatenated to update the tracking df
                list_df_global_parameters.append(df_parameters_cont_country_prov)
                list_df_global_predictions_since_today.append(df_predictions_since_today_cont_country_prov)
                list_df_global_predictions_since_100_cases.append(df_predictions_since_100_cont_country_prov)
            else:
                continue
        print("Finished the Multiprocessing for all areas")
        pool.close()
        pool.join()

    if len(list_df_global_parameters) > 0:
        pathToParam = PATH_TO_DATA_SANDBOX + f"predicted/parameters/Parameters_J&J_{day_after_yesterday}.csv"
        if path.exists(pathToParam):
            future_params_Brazil_SA_Peru_already_saved = pd.read_csv(pathToParam)
            df_global_parameters = pd.concat(
                [future_params_Brazil_SA_Peru_already_saved] + list_df_global_parameters
            ).reset_index(drop=True)
        else:
            df_global_parameters = pd.concat(
                list_df_global_parameters
            ).reset_index(drop=True)
        df_global_parameters.to_csv(pathToParam, index=False)

        df_global_predictions_since_100_cases = pd.concat(list_df_global_predictions_since_100_cases)
        #df_global_predictions_since_100_cases = DELPHIAggregations.append_all_aggregations(
        #    df_global_predictions_since_100_cases
        #)

        pathToGlobal = PATH_TO_DATA_SANDBOX + f"predicted/raw_predictions/Global_J&J_{day_after_yesterday}.csv"
        if path.exists(pathToGlobal):
            # Getting already saved Brazil, South_Africa & Peru predictions
            df_global_predictions_since_100_cases_Brazil_SA_Peru_already_saved = pd.read_csv(pathToGlobal)
            # Concatenating with these South Africa predictions
            df_global_predictions_since_100_cases_all = pd.concat([
                df_global_predictions_since_100_cases_Brazil_SA_Peru_already_saved, df_global_predictions_since_100_cases
            ]).sort_values(["Continent", "Country", "Province", "Day"]).reset_index(drop=True)
        else:
            df_global_predictions_since_100_cases_all = df_global_predictions_since_100_cases.sort_values(
                ["Continent", "Country", "Province", "Day"]
            ).reset_index(drop=True)
        # Saving concatenation
        df_global_predictions_since_100_cases_all.to_csv(pathToGlobal, index=False )
        print(f"Exported parameters and predictions for all states/provinces in J&J Study for {day_after_yesterday}")
        print("#########################################################################################################")
        print("#########################################################################################################")
    else:
        print(f"Nothing changed for {day_after_yesterday}")
        print("#########################################################################################################")
        print("#########################################################################################################")
