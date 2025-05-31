from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError

from django.shortcuts import get_object_or_404
from django.core.cache import cache
from django.db.models import Q
from django.core.paginator import Paginator
from django.db import transaction

import json


class GenericView(viewsets.ViewSet):
    """
    # GenericView
    **Required attributes**
    - queryset: the model queryset
    - serializer_class: DRF model serializer class

    **Optional attributes**
    - allowed_methods: list of allowed methods (default: ['list', 'retrieve', 'create', 'update', 'delete'])
    - allowed_filter_fields: list of allowed filter fields (default: ['*'])
    - allowed_update_fields: list of allowed update fields (default: ['*'])
    - allowed_fields: list of fields that can be selected (default: ['*'])
    - size_per_request: number of objects to return per request (default: 20)
    - permission_classes: list of permission classes
    - cache_key_prefix: cache key prefix
    - cache_duration: cache duration in seconds (default: 1 hour)

    **API endpoints**
    - GET /: list objects
    - GET /<pk>: retrieve object
    - POST /: create object
    - PUT /<pk>: update object
    - DELETE /<pk>: delete object

    **Features**
    - Pagination
    - Filtering
    - Field selection
    - Caching
    - CRUD operations
    """

    queryset = None  # the model queryset
    serializer_class = None  # DRF model serializer class
    serializer_context = {}  # serializer context
    size_per_request = 20  # number of objects to return per request
    permission_classes = []  # list of permission classes
    allowed_methods = ["list", "create", "retrieve", "update", "delete"]
    allowed_filter_fields = ["*"]  # list of allowed filter fields
    allowed_update_fields = ["*"]  # list of allowed update fields
    allowed_fields = ["*"]  # Fields that can be selected (set to ["*"] to allow all fields)
    search_fields = []

    cache_key_prefix = None  # cache key prefix
    cache_duration = 60 * 60  # cache duration in seconds
    _dynamic_serializer_class = None  # cached dynamic serializer class

    def __init__(self):
        if self.queryset is None or not self.serializer_class:
            raise NotImplementedError("queryset and serializer_class must be defined")

    # CRUD operations
    def list(self, request):
        if "list" not in self.allowed_methods:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
        
        self.crud_middleware(request)

        try:
            filters, excludes = self.parse_query_params(request)
            top, bottom, order_by = self.get_pagination_params(filters)
            fields = self.parse_fields(filters.pop("fields", None))

            cached_data = None
            if self.cache_key_prefix:
                cache_key = self.get_list_cache_key(
                    filters, excludes, top, bottom, order_by, fields
                )
                cached_data = cache.get(cache_key)
            if cached_data:
                return Response(cached_data, status=status.HTTP_200_OK)

            return self.filter(request, filters, excludes, top, bottom, order_by, fields)
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def retrieve(self, request, pk=None):
        if "retrieve" not in self.allowed_methods:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

        self.crud_middleware(request)
        fields = self.parse_fields(request.query_params.get("fields", None))

        cached_object = None
        if self.cache_key_prefix:
            cache_key = self.get_object_cache_key(pk, fields)
            cached_object = cache.get(cache_key)
        if cached_object:
            return Response(cached_object, status=status.HTTP_200_OK)

        object = self.get_serialized_object(pk, fields)
        self.cache_object(object, pk, fields)
        return Response(object, status=status.HTTP_200_OK)

    @transaction.atomic
    def create(self, request):
        if "create" not in self.allowed_methods:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
        
        self.crud_middleware(request)
        self.pre_create(request)

        serializer = self.serializer_class(data=request.data, context=self.serializer_context)
        if serializer.is_valid():
            instance = serializer.save()
            self.cache_object(serializer.data, instance.pk)
            self.invalidate_list_cache()

            self.post_create(request, instance)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @transaction.atomic
    def update(self, request, pk=None):
        if "update" not in self.allowed_methods:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

        instance = get_object_or_404(self.queryset, pk=pk)
        self.crud_middleware(request)
        self.pre_update(request, instance)

        if "*" not in self.allowed_update_fields:
            for field in request.data.keys():
                if field not in self.allowed_update_fields:
                    return Response(
                        {"error": f"Field {field} is not allowed to update"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        serializer = self.serializer_class(instance, data=request.data, partial=True, context=self.serializer_context)
        if serializer.is_valid():
            serializer.save()
            self.invalidate_object_cache(pk)
            self.invalidate_list_cache()

            self.post_update(request, instance)
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @transaction.atomic
    def destroy(self, request, pk=None):
        if "delete" not in self.allowed_methods:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

        self.crud_middleware(request)

        instance = get_object_or_404(self.queryset, pk=pk)
        self.invalidate_object_cache(pk)
        self.invalidate_list_cache()
        self.pre_destroy(instance)
        if hasattr(instance, "removed"):
            instance.removed = True
            instance.save(update_fields=["removed"])
        else:
            instance.delete()

        self.post_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # Middleware methods
    def pre_create(self, request):
        pass

    def post_create(self, request, instance):
        pass

    def pre_update(self, request, instance):
        pass

    def post_update(self, request, instance):
        pass

    def pre_destroy(self, instance):
        pass

    def post_destroy(self, instance):
        pass

    # Cache operations
    def invalidate_object_cache(self, pk):
        if not self.cache_key_prefix:
            return
        cache.delete_pattern(f"{self.cache_key_prefix}_object_{pk}_*")

    def invalidate_list_cache(self):
        if not self.cache_key_prefix:
            return
        cache.delete_pattern(f"{self.cache_key_prefix}_list_*")

    def cache_object(self, object_data, pk, fields=None):
        if not self.cache_key_prefix:
            return
        cache_key = self.get_object_cache_key(pk, fields)
        cache.set(cache_key, object_data, self.cache_duration)

    def get_object_cache_key(self, pk, fields=None):
        fields_str = ",".join(sorted(fields)) if fields else "None"
        return f"{self.cache_key_prefix}_object_{pk}_{fields_str}"

    def get_list_cache_key(self, filters, excludes, top, bottom, order_by, fields=None):
        fields_str = ",".join(sorted(fields)) if fields else "None"
        return (
            f"{self.cache_key_prefix}_list_{hash(frozenset(filters.items()))}_"
            f"{hash(frozenset(excludes.items()))}_{top}_{bottom}_{order_by}_{fields_str}"
        )

    # Helper methods
    def parse_query_params(self, request):
        filters = {}
        excludes = {}

        def parse_list_parameter(value):
            values = [v.strip() for v in value.rstrip(",").split(",") if v.strip()]
            return values if len(values) > 1 else values[0] if values else None

        def parse_value(value):
            if "," in value:
                return parse_list_parameter(value)
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value  # Return as plain string if not valid JSON

        for key, value in request.query_params.items():
            if key.startswith("exclude__"):
                parsed_value = parse_value(value)
                excludes[key[9:]] = parsed_value
            else:
                if (
                    key in self.allowed_filter_fields
                    or "*" in self.allowed_filter_fields
                ):
                    parsed_value = parse_value(value)
                    filters[key] = parsed_value

        return filters, excludes

    def parse_fields(self, fields_param):
        """Parse and validate the fields parameter."""
        if not fields_param:
            return None
            
        if isinstance(fields_param, str):
            fields = [f.strip() for f in fields_param.split(',') if f.strip()]
        elif isinstance(fields_param, list):
            fields = fields_param
        else:
            fields = [fields_param]
            
        # Filter fields based on allowed_fields
        if "*" not in self.allowed_fields:
            fields = [f for f in fields if f in self.allowed_fields]
            
        return fields if fields else None

    def get_pagination_params(self, filters):
        page = filters.pop("page", None)
        top = int(filters.pop("top", 0))
        order_by = filters.pop("order_by", None)

        if page is not None:
            top = (int(page) - 1) * self.size_per_request
        bottom = filters.pop("bottom", None)
        if bottom:
            bottom = int(bottom)
        return top, bottom, order_by

    def filter_queryset(self, filters, excludes):
        search = filters.pop("search", None)
        if search and self.search_fields:
            search_q = Q()
            for field in self.search_fields:
                search_q |= Q(**{f"{field}__icontains": search})
            filter_q = Q(**filters) & search_q
        else:
            filter_q = Q(**filters)
        exclude_q = Q(**excludes)
        return self.queryset.filter(filter_q).exclude(exclude_q)

    def filter(self, request, filters, excludes, top, bottom, order_by=None, fields=None):
        queryset = self.filter_queryset(filters, excludes)

        if order_by:
            queryset = queryset.order_by(order_by)

        paginator = Paginator(queryset, self.size_per_request)
        page_number = (top // self.size_per_request) + 1
        page = None
        if bottom is None:
            page = paginator.get_page(page_number)
        else:
            page = queryset[top:bottom]

        serializer = self.get_serializer_for_fields(page, fields, many=True)
            
        data = None
        if bottom is None:
            data = {
                "objects": serializer.data,
                "total_count": paginator.count,
                "num_pages": paginator.num_pages,
                "current_page": page.number,
            }
        else:
            data = {
                "objects": serializer.data,
                "total_count": queryset.count(),
            }

        cache_key = self.get_list_cache_key(filters, excludes, top, bottom, order_by, fields)
        cache.set(cache_key, data, self.cache_duration)

        return Response(data, status=status.HTTP_200_OK)

    def get_serializer_for_fields(self, instance, fields=None, many=False):
        """Get the appropriate serializer based on field selection."""
        if fields:
            return self.get_dynamic_fields_serializer_class()(
                instance, 
                fields=fields, 
                context=self.serializer_context, 
                many=many
            )
        else:
            return self.serializer_class(
                instance, 
                context=self.serializer_context, 
                many=many
            )

    def get_serialized_object(self, pk, fields=None):
        instance = get_object_or_404(self.queryset, pk=pk)
        serializer = self.get_serializer_for_fields(instance, fields)
        return serializer.data

    def get_dynamic_fields_serializer_class(self):
        """Return a cached version of the dynamic fields serializer class."""
        if self._dynamic_serializer_class is None:
            class DynamicFieldsModelSerializer(self.serializer_class):
                """
                A ModelSerializer that takes an additional `fields` argument that
                controls which fields should be displayed.
                """
                def __init__(self, *args, **kwargs):
                    fields = kwargs.pop("fields", None)
                    super().__init__(*args, **kwargs)
                    if fields is not None:
                        allowed = set(fields)
                        existing = set(self.fields)
                        for field_name in existing - allowed:
                            self.fields.pop(field_name)
            self._dynamic_serializer_class = DynamicFieldsModelSerializer
        return self._dynamic_serializer_class
    
    def initialize_queryset(self):
        if hasattr(self.queryset.model, 'removed'):
            self.queryset = self.queryset.filter(removed=False)

    def crud_middleware(self, request, *args, **kwargs):
        self.request = request
        self.initialize_queryset()
