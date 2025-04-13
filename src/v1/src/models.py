from typing import Optional, List, Literal, Dict
from pydantic import BaseModel

# Enum-like types
RecordType = Literal["automatic", "manual"]
CurrencyType = Literal["USD", "GBP", "EUR", "AUD", "CAD"]
EmailVerification = Literal["unverified", "verifying", "verified"]
StoreType = Literal["ebay", "shopify", "amazon"]
OrderStatus = Literal[
    "Active",
    "Cancelled",
    "CancelPending",
    "Completed",
    "CustomCode"
    "Inactive",
    "InProcess",
]


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


class PurchaseInfo(BaseModel):
    date: Optional[str]
    platform: Optional[str]
    price: Optional[float]


class IEbayInventoryItem(BaseModel):
    currency: str
    customTag: Optional[str] = None
    dateListed: str
    image: List[str]
    initialQuantity: int
    itemId: str
    lastModified: str
    name: str
    price: float
    purchase: Optional[PurchaseInfo] = None
    quantity: int
    recordType: RecordType


class IShipping(BaseModel):
    fees: float
    paymentToShipped: Optional[int] = None
    service: Optional[str] = None
    timeDays: Optional[int] = None
    trackingNumber: Optional[str] = None


class IPurchase(BaseModel):
    currency: str
    date: str
    platform: Optional[str]
    price: Optional[float]
    quantity: Optional[int]


class ISale(BaseModel):
    buyerUsername: Optional[str] = None
    currency: str
    date: str
    platform: str
    price: float
    quantity: int


class IHistory(BaseModel):
    description: str
    timestamp: str
    title: str


class IRefund(BaseModel):
    amaount: float
    currency: str
    referencedId: str
    refundedAt: str
    refundedTo: str
    status: str
    type: str


class IEbayOrder(BaseModel):
    additionalFees: float
    customTag: Optional[str]
    history: List[IHistory]
    image: List[str]
    itemId: Optional[str] = None
    lastModified: str
    listingDate: str
    name: str
    orderId: str
    purchase: IPurchase
    recordType: RecordType
    refund: Optional[IRefund]
    sale: ISale
    shipping: IShipping
    status: OrderStatus
    transactionId: str


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
