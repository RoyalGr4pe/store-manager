from pydantic import BaseModel
from typing import Optional, List, Literal

# Enum-like types
RecordType = Literal["automatic", "manual"]
CurrencyType = Literal["USD", "GBP", "EUR", "AUD", "CAD"]
EmailVerification = Literal["unverified", "verifying", "verified"]


class EbayTokenData(BaseModel):
    access_token: str
    expires_in: int
    refresh_token: str

class SuccessOrError(BaseModel):
    success: bool
    error: str

class RefreshEbayTokenData(BaseModel):
    data: Optional[EbayTokenData]
    error: Optional[str]

# --------------------------------------------------- #
# Pydantic models for user data                       #
# --------------------------------------------------- #

class ILastFetchedDate(BaseModel):
    inventory: Optional[str] = None
    orders: Optional[str] = None

class ILastFetchedDates(BaseModel):
    ebay: Optional[ILastFetchedDate] = None

class IAuthentication(BaseModel):
    emailVerified: EmailVerification


class IMetaData(BaseModel):
    image: Optional[str] = None
    createdAt: str


class IDiscord(BaseModel):
    discordId: str


class IEbay(BaseModel):
    ebayAccessToken: str
    ebayRefreshToken: str
    ebayTokenExpiry: int
    error: Optional[str] = None
    error_description: Optional[str] = None


class IConnectedAccounts(BaseModel):
    discord: Optional[IDiscord] = None
    ebay: Optional[IEbay] = None


class ISubscription(BaseModel):
    id: str
    name: str
    override: bool
    createdAt: str


class IReferral(BaseModel):
    referralCode: str
    referredBy: Optional[str] = None
    validReferrals: List[str]
    rewardsClaimed: int


class IEbayInventoryItem(BaseModel):
    itemId: str
    itemName: str
    price: float
    quantity: int
    dateListed: str
    image: List[str]
    recordType: RecordType


class IEbayOrder(BaseModel):
    additionalFees: float
    buyerUsername: str
    customTag: str
    image: List[str]
    itemName: str
    legacyItemId: str
    listingDate: str
    orderId: str
    purchaseDate: str
    purchasePlatform: str
    purchasePrice: float
    quantitySold: int
    recordType: RecordType
    saleDate: str
    salePlatform: str
    salePrice: float
    shippingFees: float


class IPreferences(BaseModel):
    preferredEmail: str
    locale: str
    currency: CurrencyType

class INumItems(BaseModel):
    automatic: int
    manual: int


# Main IUser Model
class IUser(BaseModel):
    id: str
    connectedAccounts: IConnectedAccounts
    email: str
    username: Optional[str] = None
    stripeCustomerId: str
    subscriptions: Optional[List[ISubscription]] = None
    referral: IReferral
    numListings: Optional[INumItems] = None
    numOrders: Optional[INumItems] = None
    lastFetchedDate: Optional[ILastFetchedDates] = None
    preferences: IPreferences
    authentication: IAuthentication
    metaData: IMetaData
