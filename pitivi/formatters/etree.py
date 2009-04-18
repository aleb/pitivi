# PiTiVi , Non-linear video editor
#
#       test_formatter.py
#
# Copyright (c) 2009, Edward Hervey <bilboed@bilboed.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.

import gobject
gobject.threads_init()
import gst

from xml.etree.ElementTree import Element, SubElement, tostring, parse

from pitivi.reflect import qual, namedAny
from pitivi.factories.base import SourceFactory
from pitivi.factories.file import FileSourceFactory
from pitivi.timeline.track import Track, SourceTrackObject
from pitivi.timeline.timeline import Timeline, TimelineObject
from pitivi.formatters.base import Formatter

version = "0.1"

def indent(elem, level=0):
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent(elem, level+1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i

class ElementTreeFormatterContext(object):
    def __init__(self):
        self.streams = {}
        self.factories = {}
        self.track_objects = {}
        self.rootelement = None

class ElementTreeFormatterSaveContext(ElementTreeFormatterContext):
    pass

class ElementTreeFormatterLoadContext(ElementTreeFormatterContext):
    pass

class ElementTreeFormatter(Formatter):
    _element_id = 0
    _our_properties = ["id", "type"]

    def __init__(self, *args, **kwargs):
        Formatter.__init__(self, *args, **kwargs)
        self.factoriesnode = None
        self.timelinenode = None
        self._context = ElementTreeFormatterContext()

    def _new_element_id(self):
        element_id = self._element_id
        self._element_id += 1

        return str(element_id)

    def _filterElementProperties(self, element):
        for name, value in element.attrib.iteritems():
            if name in self._our_properties:
                continue

            yield name, value

    def _parsePropertyValue(self, value):
        # nothing to read here, move along
        return gst.Caps("meh, name=%s" % value)[0]["name"]

    def _saveStream(self, stream):
        element = Element("stream")
        element.attrib["id"] = self._new_element_id()
        element.attrib["type"] = qual(stream.__class__)
        element.attrib["caps"] = str(stream.caps)

        self._context.streams[stream] = element

        return element

    def _loadStream(self, element):
        id_ = element.attrib["id"]
        klass = namedAny(element.attrib["type"])
        caps = gst.Caps(element.attrib["caps"])

        stream = klass(caps)

        self._context.streams[id_] = stream

        return stream

    def _saveStreamRef(self, stream):
        stream_element = self._context.streams[stream]
        element = Element("stream-ref")
        element.attrib["id"] = stream_element.attrib["id"]

        return element

    def _loadStreamRef(self, element):
        return self._context.streams[element.attrib["id"]]

    def _saveSource(self, source):
        element = self._saveObjectFactory(source)
        if isinstance(source, FileSourceFactory):
            return self._saveFileSourceFactory(element, source)

        return element

    def _loadFactory(self, element):
        klass = namedAny(element.attrib["type"])

        return self._loadObjectFactory(klass, element)

    def _saveObjectFactory(self, factory):
        element = Element("source")
        element.attrib["id"] = self._new_element_id()
        element.attrib["type"] = qual(factory.__class__)

        input_streams_element = SubElement(element, "input-streams")
        input_streams = factory.getInputStreams()
        for stream in input_streams:
            stream_element = self._saveStream(stream)
            input_streams_element.append(stream_element)

        output_streams_element = SubElement(element, "output-streams")
        output_streams = factory.getOutputStreams()
        for stream in output_streams:
            stream_element = self._saveStream(stream)
            output_streams_element.append(stream_element)

        self._context.factories[factory] = element

        return element

    def _loadObjectFactory(self, klass, element):
        self.debug("klass:%r, element:%r", klass, element)
        # FIXME
        if issubclass(klass, FileSourceFactory):
            factory = FileSourceFactory(element.attrib["filename"])
        else:
            factory = klass()

        input_streams = element.find("input-streams") or []
        for stream_element in input_streams:
            stream = self._loadStream(stream_element)
            factory.addInputStream(stream)

        output_streams = element.find("output-streams")
        for stream_element in output_streams:
            stream = self._loadStream(stream_element)
            factory.addOutputStream(stream)

        self._context.factories[element.attrib["id"]] = factory
        return factory

    def _saveFileSourceFactory(self, element, source):
        element.attrib["filename"] = source.filename

        return element

    def _saveFactoryRef(self, factory):
        element = Element("factory-ref")
        element.attrib["id"] = self._context.factories[factory].attrib["id"]

        return element

    def _loadFactoryRef(self, element):
        return self._context.factories[element.attrib["id"]]

    def _saveFactories(self, factories):
        element = Element("factories")
        sources = SubElement(element, "sources")
        for factory in factories:
            if isinstance(factory, SourceFactory):
                source_element = self._saveSource(factory)
                sources.append(source_element)

        return element

    def _loadFactories(self, factories, klass):
        res = []
        for fact in factories:
            res.append(self._loadObjectFactory(klass, fact))
        return res

    def _loadSources(self):
        sources = self.factoriesnode.find("sources")
        return self._loadFactories(sources, FileSourceFactory)

    def _saveTrackObject(self, track_object):
        element = Element("track-object")
        element.attrib["id"] = self._new_element_id()
        element.attrib["type"] = qual(track_object.__class__)
        for attribute in ("start", "duration",
                "in_point", "media_duration"):
            element.attrib[attribute] = \
                    str("(gint64)%s" % getattr(track_object, attribute))

        element.attrib["priority"] = "(int)%s" % track_object.priority

        factory_ref = \
                self._saveFactoryRef(track_object.factory)
        stream_ref = self._saveStreamRef(track_object.stream)

        element.append(factory_ref)
        element.append(stream_ref)

        self._context.track_objects[track_object] = element

        return element

    def _loadTrackObject(self, element):
        self.debug("%r", element)
        klass = namedAny(element.attrib["type"])

        factory_ref = element.find("factory-ref")
        factory = self._loadFactoryRef(factory_ref)

        stream_ref = element.find("stream-ref")
        stream = self._loadStreamRef(stream_ref)

        track_object = klass(factory, stream)
        for name, value_string in self._filterElementProperties(element):
            value = self._parsePropertyValue(value_string)
            setattr(track_object, name, value)

        self._context.track_objects[element.attrib["id"]] = track_object
        return track_object

    def _saveTrackObjectRef(self, track_object):
        element = Element("track-object-ref")
        element.attrib["id"] = self._context.track_objects[track_object].attrib["id"]

        return element

    def _loadTrackObjectRef(self, element):
        self.debug("%r", element)
        return self._context.track_objects[element.attrib["id"]]

    def _saveTrackObjectRefs(self, track_objects):
        element = Element("track-object-refs")

        for track_object in track_objects:
            track_object_ref = self._saveTrackObjectRef(track_object)
            element.append(track_object_ref)

        return element

    def _loadTrackObjectRefs(self, element):
        self.debug("%r", element)
        track_objects = []
        for track_object_element in element:
            track_object = self._loadTrackObjectRef(track_object_element)
            track_objects.append(track_object)

        return track_objects

    def _saveTrack(self, track):
        element = Element("track")
        stream_element = self._saveStream(track.stream)
        element.append(stream_element)
        track_objects = SubElement(element, "track-objects")

        for track_object in track.track_objects:
            if track_object is track.default_track_object:
                continue

            track_object_element = self._saveTrackObject(track_object)
            track_objects.append(track_object_element)

        return element

    def _loadTrack(self, element):
        self.debug("%r", element)
        stream_element = element.find("stream")
        stream = self._loadStream(stream_element)

        track = Track(stream)

        track_objects_element  = element.find("track-objects")
        for track_object_element in track_objects_element:
            track_object = self._loadTrackObject(track_object_element)
            track.addTrackObject(track_object)

        return track

    def _saveTracks(self, tracks):
        element = Element("tracks")
        for track in tracks:
            track_element = self._saveTrack(track)
            element.append(track_element)

        return element

    def _loadTracks(self, element):
        self.debug("element:%r", element)
        tracks = []
        for track_element in element:
            track = self._loadTrack(track_element)
            tracks.append(track)

        return tracks

    ## TimelineObjects

    def _saveTimelineObject(self, timeline_object):
        element = Element("timeline-object")
        factory_ref = self._saveFactoryRef(timeline_object.factory)
        element.append(factory_ref)
        track_object_refs = \
                self._saveTrackObjectRefs(timeline_object.track_objects)
        element.append(track_object_refs)

        return element

    def _loadTimelineObject(self, element):
        factory_ref = element.find("factory-ref")
        factory = self._loadFactoryRef(factory_ref)

        timeline_object = TimelineObject(factory)
        track_object_refs_element = element.find("track-object-refs")
        track_objects = \
                self._loadTrackObjectRefs(track_object_refs_element)

        for track_object in track_objects:
            timeline_object.addTrackObject(track_object)

        return timeline_object

    def _saveTimelineObjects(self, timeline_objects):
        element = Element("timeline-objects")
        for timeline_object in timeline_objects:
            timeline_object_element = self._saveTimelineObject(timeline_object)
            element.append(timeline_object_element)

        return element

    def _loadTimelineObjects(self, element):
        timeline_objects = []
        for timeline_object_element in element:
            timeline_object = \
                    self._loadTimelineObject(timeline_object_element)
            timeline_objects.append(timeline_object)

        return timeline_objects

    ## Timeline

    def _saveTimeline(self, timeline):
        element = Element("timeline")

        tracks = self._saveTracks(timeline.tracks)
        element.append(tracks)

        timeline_objects = \
                self._saveTimelineObjects(timeline.timeline_objects)
        element.append(timeline_objects)

        return element

    def _loadTimeline(self, element):
        self.debug("element:%r", element)

        timeline = self.project.timeline

        # Tracks
        tracks_element = element.find("tracks")
        tracks = self._loadTracks(tracks_element)

        # Timeline Object
        timeline_objects_element = element.find("timeline-objects")
        timeline_objects = \
                self._loadTimelineObjects(timeline_objects_element)

        for track in tracks:
            timeline.addTrack(track)

        # add the timeline objects
        for timeline_object in timeline_objects:
            # NOTE: this is a low-level routine that simply appends the
            # timeline object to the timeline list. It doesn't ensure all the
            # child track objects have been added to their respective tracks.
            timeline.addTimelineObject(timeline_object)

        return timeline

    ## Main methods

    def _saveMainTag(self):
        element = Element("pitivi")
        element.attrib["formatter"] = "etree"
        element.attrib["version"] = version

        return element

    def _serializeProject(self, project):
        root = self._saveMainTag()

        factories = project.sources.sources.values()
        factories_element = self._saveFactories(factories)
        root.append(factories_element)

        timeline_element = self._saveTimeline(project.timeline)
        root.append(timeline_element)
        return root

    ## Formatter method implementations

    def _saveProject(self, project, location):
        root = self._serializeProject(project)
        f = file(location.split('file://')[1], "w")
        indent(root)
        f.write(tostring(root))
        f.close()

    def _parse(self, location):
        self.debug("location:%s", location)
        # open the given location
        self._context.rootelement = parse(location.split('://', 1)[1])
        self.factoriesnode = self._context.rootelement.find("factories")
        self.timelinenode = self._context.rootelement.find("timeline")

    def _getSources(self):
        self.debug("%r", self)
        return self._loadSources()

    def _fillTimeline(self):
        # fill up self.project
        self._loadTimeline(self.timelinenode)

    @classmethod
    def canHandle(cls, uri):
        return uri.endswith(".xptv")
