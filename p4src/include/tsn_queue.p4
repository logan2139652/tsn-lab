/*
 * Copyright 2017-present Open Networking Foundation
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef __TSN_QUEUE__
#define __TSN_QUEUE__

#include "headers.p4"
#include "defines.p4"

control tsn_queue_control(inout headers_t hdr,
                          inout local_metadata_t local_metadata,
                          inout standard_metadata_t standard_metadata) {

    action remap_tsn_cycle() {
        if (hdr.tsn.cycle_tag == 8w0) {
            hdr.tsn.cycle_tag = 8w1;
        } else if (hdr.tsn.cycle_tag == 8w1) {
            hdr.tsn.cycle_tag = 8w2;
        } else if (hdr.tsn.cycle_tag == 8w2) {
            hdr.tsn.cycle_tag = 8w4;
        } else if (hdr.tsn.cycle_tag == 8w3) {
            hdr.tsn.cycle_tag = 8w4;
        } else if (hdr.tsn.cycle_tag == 8w4) {
            hdr.tsn.cycle_tag = 8w5;
        } else if (hdr.tsn.cycle_tag == 8w5) {
            hdr.tsn.cycle_tag = 8w6;
        } else {
            hdr.tsn.cycle_tag = 8w0;
        }
        local_metadata.cycle_tag = hdr.tsn.cycle_tag;
    }

    action set_base_queue_from_cycle() {
        if (hdr.tsn.kind == 8w2) {
            local_metadata.base_queue = 8w0;
        } else if (hdr.tsn.cycle_tag[2:0] == 3w0 ||
                   hdr.tsn.cycle_tag[2:0] == 3w4) {
            local_metadata.base_queue = 8w1;
        } else if (hdr.tsn.cycle_tag[2:0] == 3w1 ||
                   hdr.tsn.cycle_tag[2:0] == 3w5) {
            local_metadata.base_queue = 8w2;
        } else if (hdr.tsn.cycle_tag[2:0] == 3w2 ||
                   hdr.tsn.cycle_tag[2:0] == 3w6) {
            local_metadata.base_queue = 8w3;
        } else {
            local_metadata.base_queue = 8w0;
        }
    }

    action set_priority_from_queue() {
        if (local_metadata.base_queue == 8w1) {
            standard_metadata.priority = 3w6;
        } else if (local_metadata.base_queue == 8w2) {
            standard_metadata.priority = 3w5;
        } else if (local_metadata.base_queue == 8w3) {
            standard_metadata.priority = 3w4;
        } else {
            standard_metadata.priority = 3w7;
        }
    }

    apply {
        if (hdr.tsn.isValid()) {
            if (hdr.tsn.kind != 8w2) {
                remap_tsn_cycle();
            }
            set_base_queue_from_cycle();
            set_priority_from_queue();
        } else {
            standard_metadata.priority = 3w7;
        }
    }
}

control tsn_debug_egress_control(inout headers_t hdr,
                                 inout local_metadata_t local_metadata,
                                 inout standard_metadata_t standard_metadata) {
    apply {
        if (hdr.tsn.isValid()) {
            hdr.tsn.flags = hdr.tsn.cycle_tag;
        }
    }
}

#endif
