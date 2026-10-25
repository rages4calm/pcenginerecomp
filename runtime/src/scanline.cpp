#include "pce/scanline.hpp"
#include "pce/runtime.hpp"
#include <algorithm>
#include <limits>

namespace pce {
void VideoOutput::prepare_frame(const Vdc& vdc) {
    back_.width=vdc.raster.horizontal[1];
    back_.height=vdc.raster.vertical[1];
    if(!back_.width || back_.width>1024 || !back_.height || back_.height>512)
        throw Fault("continuous video frame geometry exceeds bounded buffers");
    back_.rgb.resize(static_cast<std::size_t>(back_.width)*back_.height*3);
    std::fill(back_.rgb.begin(),back_.rgb.end(),0);
}
void VideoOutput::enable(const Vdc& vdc) {
    if(!vdc.enabled || !vdc.raster.enabled)
        throw Fault("continuous video requires the raster profile");
    if(vdc.raster.master_ticks!=0)
        throw Fault("continuous video must be enabled before guest execution");
    *this=VideoOutput{};
    enabled=true;
    // Reserve once: geometry changes cannot trigger geometric vector growth or
    // unbounded allocation in the guest-clock path.
    constexpr std::size_t max_bytes=1024*512*3;
    front_.rgb.reserve(max_bytes);back_.rgb.reserve(max_bytes);
    control_=vdc.reg[5];mode_=vdc.reg[9];
    burst_=(control_&192)==0;
    scroll_x_=vdc.reg[7];scroll_y_=counter_y_=vdc.reg[8];
    prepare_frame(vdc);
}
void VideoOutput::register_write(const Vdc&, unsigned index, bool) {
    if(index==8) y_pending_=true;
}
void VideoOutput::latch_y(const Vdc& vdc) {
    if(!enabled) return;
    if(vdc.raster.raster_line==0) counter_y_=vdc.reg[8];
    else if(y_pending_) {
        counter_y_=static_cast<std::uint16_t>(vdc.reg[8]+1);
        y_pending_=false;
    } else if(increment_) ++counter_y_;
    scroll_y_=counter_y_;increment_=false;
}
void VideoOutput::latch_x(const Vdc& vdc) { if(enabled) scroll_x_=vdc.reg[7]; }
void VideoOutput::latch_mode(const Vdc& vdc) { if(enabled) mode_=vdc.reg[9]; }
void VideoOutput::increment_y() { if(enabled) increment_=true; }
void VideoOutput::horizontal_start(const Vdc& vdc) {
    if(enabled && !burst_) control_=vdc.reg[5];
}
void VideoOutput::begin_line(const Vdc& vdc) {
    if(!enabled) return;
    row_=vdc.raster.raster_line;x_=0;
    line_width_=vdc.raster.horizontal[1];
    active_=vdc.raster.v_state==1 && row_<back_.height;
    if(!active_) return;
    if(line_width_>indices_.size()) throw Fault("continuous video line geometry exceeds bound");
    ++lines_rendered_;
    if(!burst_) render_scanline_indices(vdc,row_,scroll_x_,scroll_y_,control_,mode_,
                                      std::span(indices_).first(line_width_));
}
void VideoOutput::pixel(const Vdc& vdc, const Vce& vce) {
    if(!enabled || !active_ || vdc.raster.h_state!=1 || x_>=line_width_) return;
    const auto x=x_++;
    if(x>=back_.width) return;
    ++pixels_rendered_;
    if(burst_) return;
    const auto rgb=vce_rgb(vce.palette[indices_[x]],vce.control);
    const auto offset=(static_cast<std::size_t>(row_)*back_.width+x)*3;
    for(unsigned channel=0;channel<3;++channel) back_.rgb[offset+channel]=rgb[channel];
}
void VideoOutput::end_line() { active_=false; }
void VideoOutput::frame_boundary(const Vdc& vdc) {
    if(!enabled) return;
    if(sequence_==std::numeric_limits<std::uint64_t>::max())
        throw Fault("continuous video sequence overflow");
    std::swap(front_,back_);
    ++sequence_;completed_ticks_=vdc.raster.master_ticks;
    control_=(control_&~192)|(vdc.reg[5]&192);
    burst_=(vdc.reg[5]&192)==0;
    prepare_frame(vdc);
}
void Bus::enable_continuous_video() {
    enable_video();
    vdc.video.enable(vdc);
}
} // namespace pce
