import json



# Determines how many listings and orders each subscription user can have
def fetch_sub_limits_dict(filename="sub-limits.json"):
    with open(filename, "r") as file:
        return json.load(file)



def fetch_users_limits(sub_name, limit_type):
    sub_limits_dict = fetch_sub_limits_dict()
    limits = sub_limits_dict[limit_type]

    # Extract the first work of the subscription
    # i.e. Standard - member -> standard
    formatted_sub_name = sub_name.split(" ")[0].lower()

    # Dict which looks something like for listings
    # {
    #    "automatic": 300,
    #    "manual": 300
    # }
    return limits[formatted_sub_name]



def calc_user_set_limit(user_set_limit, subscription_max_records, maximum_records_per_request=60):    
    # user_set_limit is not allowed to be greater than subscription_max_records
    # If this is the case then set user_set_limit to subscription_max_records
    if user_set_limit > subscription_max_records:
        user_set_limit = subscription_max_records

    # user_set_limit is not allowed to be greater then maximum_sales_per_request
    # If this is the case then set user_set_limit to maximum_sales_per_request
    if user_set_limit > maximum_records_per_request: # User is not allowed to do this
        user_set_limit = maximum_records_per_request

    return user_set_limit



def filter_return_records(ebay_records, current_records, id_key):
    # Create a dictionary from current_records using id_key for comparison
    record_dict = {record[id_key]: record for record in current_records if id_key in record}

    # Iterate through ebay_records and add those not already in record_dict
    for ebay_record in ebay_records:
        if ebay_record.get(id_key) and ebay_record[id_key] not in record_dict:
            record_dict[ebay_record[id_key]] = ebay_record

    # Convert the values of the dictionary back to a list
    return_list = list(record_dict.values())

    return return_list