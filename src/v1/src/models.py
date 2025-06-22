from typing import Optional, List, Literal, Union
from pydantic import BaseModel, Field

# Enum-like types
RecordType = Literal["automatic", "manual"]
CurrencyType = Literal["USD", "GBP", "EUR", "AUD", "CAD"]
EmailVerification = Literal["unverified", "verifying", "verified"]
ItemType = Literal["inventory", "orders"]
IdKey = Literal["transactionId", "itemId"]
StoreType = Literal["ebay", "shopify", "amazon", "depop"]
OrderStatus = Literal[
    "Active",
    "Cancelled",
    "CancelPending",
    "Completed",
    "CustomCode"
    "Inactive",
    "InProcess",
]
Condition = Union[Literal["new", "used", "open-box", "refurbished"], str]

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

class ICustomEbayData(BaseModel):
    type: Optional[str] = None


class ICustomDepopData(BaseModel):
    discountedPrice: Optional[str] = None
    sizes: Optional[str] = None
    brandId: Optional[str] = None
    categoryId: Optional[str] = None
    variantSetId: Optional[str] = None
    variants: Optional[str] = None


class IInventoryItem(BaseModel):
    name: Optional[str] = None
    ebay: Optional[ICustomEbayData] = None
    price: Optional[float] = None
    image: Optional[List[str]] = None
    depop: Optional[ICustomEbayData] = None
    itemId: Optional[str] = None
    currency: Optional[str] = None
    quantity: Optional[int] = None
    purchase: Optional[PurchaseInfo] = None
    condition: Optional[Condition] = None
    customTag: Optional[str] = None
    createdAt: Optional[str] = None
    storeType: Optional[StoreType] = None
    dateListed: Optional[str] = None
    recordType: Optional[RecordType] = None
    lastModified: Optional[str] = None
    storageLocation: Optional[str] = None
    initialQuantity: Optional[int] = None


class ITaxes(BaseModel):
    amount: Optional[float] = None
    type: Optional[str] = None
    description: Optional[str] = None
    currency: Optional[str] = None

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
    status: OrderStatus
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


class IOrder(BaseModel):
    tax: Optional[ITaxes] = None
    name: str
    sale: Optional[ISale] = None
    depop: Optional[ICustomDepopData] = None
    image: Optional[List[str]] = None
    status: OrderStatus
    itemId: Optional[str] = None
    refund: Optional[IRefund] = None
    history: Optional[List[IHistory]] = None
    orderId: Optional[str] = None
    shipping: Optional[IShipping] = None
    purchase: Optional[IPurchase] = None
    customTag: Optional[str] = None
    createdAt: Optional[str] = None
    condition: Optional[Condition] = None
    storeType: Optional[StoreType] = None
    recordType: RecordType
    listingDate: Optional[str] = None
    lastModified: str
    transactionId: str
    additionalFees: Optional[float] = None
    storageLocation: Optional[str] = None
    buyerAdditionalFees: Optional[float] = None


# --------------------------------------------------- #
# Pydantic models for user data                       #
# --------------------------------------------------- #


class ILastFetchedDate(BaseModel):
    inventory: Optional[str] = None
    orders: Optional[str] = None


class IOffset(BaseModel):
    inventory: Optional[str] = None
    orders: Optional[str] = None


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

class IStockX(BaseModel):
    stockxAccessToken: str
    stockxRefreshToken: str
    stockxTokenExpiry: int
    error: Optional[str] = None
    error_description: Optional[str] = None

class IDepop(BaseModel):
    shopId: str

class IConnectedAccounts(BaseModel):
    discord: Optional[IDiscord] = None
    ebay: Optional[IEbay] = None
    depop: Optional[IDepop] = None
    stockx: Optional[IStockX] = None

class ISubscription(BaseModel):
    id: str
    name: str
    override: bool
    createdAt: str


class IReferral(BaseModel):
    referralCode: Optional[str] = None
    referredBy: Optional[str] = None
    validReferrals: Optional[List[str]] = None
    rewardsClaimed: Optional[int] = None


class IPreferences(BaseModel):
    locale: Optional[str] = None
    currency: Optional[CurrencyType] = None


class INumListings(BaseModel):
    automatic: Optional[int] = None
    manual: Optional[int] = None

class INumOrders(BaseModel):
    resetDate: Optional[str] = None
    automatic: Optional[int] = None
    manual: Optional[int] = None
    totalAutomatic: Optional[int] = None
    totalManual: Optional[int] = None


class StoreEntry(BaseModel):
    lastFetchedDate: Optional[ILastFetchedDate] = None
    offset: Optional[IOffset] = None

class IStore(BaseModel):
    numListings: Optional[INumListings] = None
    numOrders: Optional[INumOrders] = None

    storeMeta: dict[str, StoreEntry] = Field(default_factory=dict)


# Main IUser Model
class IUser(BaseModel):
    id: str
    connectedAccounts: IConnectedAccounts
    email: str
    username: Optional[str] = None
    stripeCustomerId: str
    subscriptions: Optional[List[ISubscription]] = None
    referral: IReferral
    store: Optional[IStore] = None
    preferences: IPreferences
    authentication: IAuthentication
    metaData: IMetaData
