"""Izvori oglasa. Svaki izvor vraća listu Listing objekata."""

from .base import Source
from .burza import Burza
from .fina import Fina
from .index_oglasi import IndexOglasi
from .nekretnine_hr import NekretnineHr
from .njuskalo import Njuskalo
from .oglasnik import Oglasnik
from .realestatecroatia import RealEstateCroatia
from .vender import Vender

ALL: dict[str, type[Source]] = {
    NekretnineHr.name: NekretnineHr,
    IndexOglasi.name: IndexOglasi,
    Oglasnik.name: Oglasnik,
    Fina.name: Fina,
    Vender.name: Vender,
    Njuskalo.name: Njuskalo,
    RealEstateCroatia.name: RealEstateCroatia,
    Burza.name: Burza,
}
