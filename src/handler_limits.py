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