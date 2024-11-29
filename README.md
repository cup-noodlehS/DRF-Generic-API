# Django Generic Viewset

A powerful, feature-rich generic viewset for Django REST Framework that provides out-of-the-box support for:

-   Pagination
-   Filtering
-   Caching
-   CRUD operations

## Installation

```bash
pip install django-generic-viewset
```

## Quick Start

```python
from rest_framework import serializers
from django_generic_viewset.views import GenericView
from .models import YourModel

class YourModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = YourModel
        fields = '__all__'

class YourModelViewSet(GenericView):
    queryset = YourModel.objects.all()
    serializer_class = YourModelSerializer

    # Optional customizations
    size_per_request = 10
    cache_key_prefix = 'your_model'
    allowed_filter_fields = ['name', 'status']
```

## Features

### Filtering

Filter your querysets easily:

-   `GET /?name=John`: Filter by exact match
-   `GET /?name=John,Jane`: Multiple value filter
-   `GET /?exclude__status=draft`: Exclude specific values

### Pagination

-   `GET /?page=2`: Paginate results
-   `GET /?top=20&bottom=40`: Custom pagination
-   `GET /?order_by=name`: Order results

### Caching

Automatic caching of list and object views with configurable key prefixes and durations.

## License

MIT License
