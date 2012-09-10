from copy import copy

from django.core.exceptions import ValidationError

from .registry import app_registry
from .forms import AppDataForm

class AppDataContainerFactory(dict):
    def __init__(self, model, *args, **kwargs):
        self._model = model
        self._app_registry = kwargs.pop('app_registry', app_registry)
        super(AppDataContainerFactory, self).__init__(*args, **kwargs)

    def __setattr__(self, name, value):
        if name.startswith('_') or self._app_registry.get_class(name, self._model) is None:
            super(AppDataContainerFactory, self).__setattr__(name, value)
        else:
            self[name] = copy(value)

    def __getattr__(self, name):
        if name.startswith('_') or self._app_registry.get_class(name, self._model) is None:
            raise AttributeError()
        return self[name]

    def __getitem__(self, name):
        class_ = self._app_registry.get_class(name, self._model)
        try:
            val = super(AppDataContainerFactory, self).__getitem__(name)
        except KeyError:
            if class_ is None:
                raise
            val = class_()
            self[name] = val
        else:
            if class_ is not None and not isinstance(val, class_):
                val = class_(val)
                self[name] = val

        return val

    def validate(self, model_instance):
        errors = {}
        for key, value in self.items():
            if hasattr(value, 'validate') and getattr(value, 'accessed', True):
                try:
                    value.validate(self, model_instance)
                except ValidationError, e:
                    errors[key] = e.message_dict
        if errors:
            raise ValidationError(errors)

    def serialize(self):
        for key, value in self.items():
            if hasattr(value, 'serialize') and getattr(value, 'accessed', True):
                super(AppDataContainerFactory, self).__setitem__(key, value.serialize())
        # return a copy so that it's a fresh dict, not AppDataContainerFactory
        return self.copy()

    def get(self, name, default=None):
        if name in self:
            return self[name]

        if default is None:
            return None

        class_ = self._app_registry.get_class(name, self._model)
        if class_ is not None and not isinstance(default, class_):
            return class_(default)

        return default


INITIAL = object()

class AppDataContainer(object):
    form_class = AppDataForm

    @classmethod
    def from_form(cls, form_class):
        return type('%sAppDataContainer' % form_class.__name__, (cls, ), {'fields': {}, 'form_class': form_class})

    @property
    def accessed(self):
        return self._accessed

    def __init__(self, *args, **kwargs):
        self._data = dict(*args, **kwargs)
        self._attr_cache = {}
        self._accessed = False

    def __eq__(self, other):
        if isinstance(other, AppDataContainer):
            #FIXME: _attr_cache
            return self._data == other._data
        elif isinstance(other, dict):
            return other == self._data
        return False

    @property
    def _form(self):
        if not hasattr(self, '_form_instance'):
            self._form_instance = self.get_form(self._data)
            self._form_instance.is_valid()
            # FIXME: what to do if invalid?
        return self._form_instance

    def __setitem__(self, name, value):
        self._accessed = True
        if name in self._form.fields:
            # store the original
            self._attr_cache[name] = value
        else:
            self._data[name] = value

    def __setattr__(self, name, value):
        if name.startswith('_'):
            super(AppDataContainer, self).__setattr__(name, value)
        else:
            self.__setitem__(name, value)

    def __getitem__(self, name):
        self._accessed = True
        if name in self._form.fields and name in self._data:
            self._attr_cache[name] = self._form.cleaned_data[name]

        if name in self._attr_cache:
            return self._attr_cache[name]

        return self._data[name]

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError()
        try:
            return self.__getitem__(name)
        except KeyError:
            raise AttributeError()

    def __delitem__(self, name):
        self._accessed = True
        if name in self._attr_cache:
            del self._attr_cache[name]
        del self._data[name]

    def get(self, name, default=INITIAL):
        try:
            return self[name]
        except KeyError:
            if default is INITIAL and name in self._form.fields:
                return self._form.fields[name].initial
            return default

    def update(self, data):
        for k, v in data.iteritems():
            self[k] = v

    def validate(self, app_data, model_instance):
        self.serialize()
        form = self.get_form(self._data)
        if not form.is_valid():
            raise ValidationError(form.errors)

    def serialize(self):
        for name, value in self._attr_cache.iteritems():
            f = self._form.fields[name]
            value = f.prepare_value(value)
            if hasattr(f.widget, '_format_value'):
                value = f.widget._format_value(value)
            self._data[name] = value
        return self._data

    def get_form(self, data=None, files=None, fields=(), exclude=(), form_class=None, **kwargs):
        form_class = form_class or self.form_class
        return form_class(self, data, files, fields=fields, exclude=exclude, **kwargs)
