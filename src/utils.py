from src.models import IUser, ISubscription


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
