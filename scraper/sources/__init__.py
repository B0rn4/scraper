"""Izvori oglasa. Svaki izvor vraća listu Listing objekata."""

from .base import Source
from .fina import Fina
from .index_oglasi import IndexOglasi
from .nekretnine_hr import NekretnineHr
from .oglasnik import Oglasnik

ALL: dict[str, type[Source]] = {
    NekretnineHr.name: NekretnineHr,
    IndexOglasi.name: IndexOglasi,
    Oglasnik.name: Oglasnik,
    Fina.name: Fina,
}
