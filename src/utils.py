from src.models import IUser, ISubscription

from datetime import datetime, timezone

import json

def fetch_user_member_sub(user: IUser) -> ISubscription | None:
    user_subscriptions_list = user.subscriptions
    if not user_subscriptions_list:
        return False

    user_has_member_subscription = False
    user_subscription = None

    for sub in user_subscriptions_list:
        if "member" in sub.name:
            user_has_member_subscription = True
            user_subscription = sub
            break

    if not user_has_member_subscription:
        return False

    return user_subscription


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


def get_next_month_reset_date() -> str:
    """Returns the first of the next month as an ISO string."""
    # Use timezone-aware datetime with UTC
    today = datetime.now(timezone.utc)

    # Calculate the first day of the next month
    if today.month == 12:
        next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month + 1, day=1)

    # Return the date as an ISO string in UTC format
    return next_month.isoformat()
