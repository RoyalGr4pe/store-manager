from typing import Optional, List, Literal, Dict
from pydantic import BaseModel

# Enum-like types
RecordType = Literal["automatic", "manual"]
CurrencyType = Literal["USD", "GBP", "EUR", "AUD", "CAD"]
EmailVerification = Literal["unverified", "verifying", "verified"]
StoreType = Literal["ebay", "shopify", "amazon"]
OrderStatus = Literal["Active", "Completed", "Cencelled", "Inactive", "Shipped", "InProcess", "Invalid"]


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


class IEbayInventoryItem(BaseModel):
    initialQuantity: int
    itemId: str
    itemName: str
    price: float
    quantity: int
    dateListed: str
    image: List[str]
    recordType: RecordType


class IShipping(BaseModel):
    fees: float
    paymentToShipped: int
    service: str
    timeDays: int
    trackingNumber: str


class IPurchase(BaseModel):
    date: str
    platform: str
    price: float
    quantity: int

class ISale(BaseModel):
    buyerUsername: str
    date: str
    platform: str
    price: float
    quantity: int

class IEbayOrder(BaseModel):
    additionalFees: float
    customTag: str
    image: List[str]
    itemName: str
    legacyItemId: str
    listingDate: str
    orderId: str
    purchase: IPurchase
    recordType: RecordType
    sale: ISale
    shipping: IShipping
    status: OrderStatus


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


class IPreferences(BaseModel):
    preferredEmail: str
    locale: str
    currency: CurrencyType


class INumListings(BaseModel):
    automatic: int
    manual: int

class INumOrders(BaseModel):
    resetDate: str
    automatic: int
    manual: int
    totalAutomatic: int
    totalManual: int


class IStore(BaseModel):
    numListings: Optional[INumListings] = None
    numOrders: Optional[INumOrders] = None
    lastFetchedDate: Optional[ILastFetchedDate] = None


class Store(BaseModel):
    ebay: Optional[IStore] = None

# Main IUser Model
class IUser(BaseModel):
    id: str
    connectedAccounts: IConnectedAccounts
    email: str
    username: Optional[str] = None
    stripeCustomerId: str
    subscriptions: Optional[List[ISubscription]] = None
    referral: IReferral
    store: Optional[Store] = None
    preferences: IPreferences
    authentication: IAuthentication
    metaData: IMetaData
